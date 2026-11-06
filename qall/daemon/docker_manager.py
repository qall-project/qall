# Copyright 2026 Scaleway
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import shutil
import docker
import os

from pathlib import Path
from typing import Iterator, Optional

from docker.errors import DockerException, APIError, ImageNotFound, NotFound
from docker.models.containers import Container

from qall.config.paths import (
    DEFAULT_BLOCK_REGISTRY_PATH,
    DEFAULT_ARTIFACT_REGISTRY_PATH,
    host_volumes_root,
)

from .base_manager import BaseDaemonManager

logger = logging.getLogger(__name__)

_DEFAULT_IMAGE = "scw/qall-daemon:latest"
# _DEFAULT_IMAGE = "rg.fr-par.scw.cloud/qall-project/qall-daemon:latest"

# In-container paths where the host block/artifact registries are bind-mounted.
# The daemon reads its local block store / writes artifacts & its metadata DB
# from these (flags `-block-registry-dir` / `-artifact-registry-dir`).
_BLOCK_REGISTRY_MOUNT = "/block-registry"
_ARTIFACT_REGISTRY_MOUNT = "/artifact-registry"

# Docker daemon flag telling the daemon where the host volume root lives (both
# on the host and at the exact same path inside the daemon container).
_HOST_VOLUMES_ROOT_FLAG = "--host-volumes-root"


def dataloader_volumes_dir(root: Path | None = None) -> Path:
    """
    Host directory under which the daemon creates one sub-directory per
    ``(workflow_run_id, dataloader_name)`` pair backing its rclone volumes.

    Single source of truth for the bind mount, the daemon flag and the tests:
    it derives from :func:`qall.config.paths.host_volumes_root` (env-overridable
    via ``QALL_HOST_VOLUMES_ROOT``) and canonicalises the resulting path so it
    matches the string handed to Docker (macOS: ``/tmp`` -> ``/private/tmp``).
    """
    base = Path(root) if root is not None else host_volumes_root()
    return base.resolve() / "dataloaders"


class DockerDaemonManager(BaseDaemonManager):
    """
    Manages the lifecycle of the local Qall Daemon via Docker.
    """

    def __init__(
        self,
        grpc_port: int = 50053,
        http_port: int = 8080,
        local: bool = True,
        host_block_registry_path: str | Path = DEFAULT_BLOCK_REGISTRY_PATH,
        host_artifact_registry_path: str | Path = DEFAULT_ARTIFACT_REGISTRY_PATH,
    ):
        self.grpc_port = grpc_port
        self.http_port = http_port
        self.__image = _DEFAULT_IMAGE
        self.__container_name = "qalld"
        self.__ports = {"50053/tcp": self.grpc_port, "8080/tcp": self.http_port}
        self.__local = local
        self.__host_block_registry_path = str(host_block_registry_path)
        self.__host_artifact_registry_path = str(host_artifact_registry_path)

        # Ad-hoc host directories bind-mounted 1:1 into the daemon container.
        # The root is canonicalised ONCE here: on macOS `/tmp` is a symlink to
        # `/private/tmp`, and the very same string must be used as the bind
        # source, the bind target and the daemon flag so the host, the
        # containerised daemon and the containerd/rclone plugin all agree.
        root = host_volumes_root().resolve()
        self.__host_volumes_root = str(root)

        # Temporary fix to create the necessary unifs volume while the daemon is still dockerized.
        # Remove this line once the daemon is out of its container and can run its own unifs creation logic.
        self.__unifs = root / "unifs"
        # Per-(workflow_run_id, dataloader_name) bookkeeping for the volumes the
        # daemon creates through the rclone Docker volume plugin.
        self.__dataloaders = dataloader_volumes_dir(root)

        try:
            self.__docker_client = docker.from_env()
        except DockerException as e:
            raise RuntimeError(
                "Docker does not seem to be running or accessible on this machine."
            ) from e

        self.__container = None

    @property
    def container(self) -> Container | None:
        return self.__container

    def is_running(self) -> bool:
        """
        Return True when a daemon container is running and manageable.
        """
        return self.attach()

    def attach(self) -> bool:
        """
        Attach the current DockerDaemonManager instance to a running daemon container, if it exists.
        """
        containers = self.__docker_client.containers.list(
            filters={"status": "running", "name": self.__container_name}
        )
        if len(containers) == 1:
            self.__container = containers[0]
            return True
        return False

    def stop(self):
        """
        Stop and cleanup the daemon container.
        """
        if self.__container:
            logger.info("Stopping and cleaning up the Qall Daemon...")
            try:
                self.__container.stop(timeout=5)
                self.__container.remove()
                self._teardown_host_volumes()
                logger.info("Cleanup complete.")
            except APIError as e:
                logger.warning(f"Failed to cleanly remove the container: {e}")
            return

    def logs(self) -> Optional[Iterator[str]]:
        """
        Stream the log lines of the daemon container.
        """
        if self.__container:
            try:
                return (
                    line.decode("utf-8", errors="replace")
                    for line in self.__container.logs(stream=True)
                )
            except APIError as e:
                logger.error(f"Failed to retrieve logs: {e}")

    def task_logs(self, task_run_id: str) -> tuple[str, str]:
        """
        Retrieve the stdout/stderr of a task container, if it still exists.

        Task containers are named ``qall-task-<task_run_id[:8]>`` and are kept
        around after execution, so their logs remain available for inspection
        once a task has finished (successfully or not). Missing containers
        yield empty strings.
        """
        container_name = f"qall-task-{task_run_id[:8]}"

        try:
            container = self.__docker_client.containers.get(container_name)
        except NotFound:
            return "", ""

        try:
            stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")
        except APIError as e:
            logger.warning(f"Failed to retrieve logs for {container_name}: {e}")
            return "", ""

        return stdout, stderr

    def _start_daemon(self):
        """
        Creates and start a container with our local daemon server.
        """
        logger.info(f"Starting Qall daemon (from {self.__image})...")

        self._cleanup_existing_container()
        self._ensure_image_exists()

        try:
            command = [
                f"--host-task-dir={self.__host_block_registry_path}",
                # The daemon's own block/artifact stores must resolve to the
                # mounted volumes *inside* the daemon container (this is the
                # dockerized daemon). -host-task-dir stays the host path:
                # docker resolves that bind source on the host when it spawns
                # task containers via /var/run/docker.sock.
                f"--block-registry-dir={_BLOCK_REGISTRY_MOUNT}",
                f"--artifact-registry-dir={_ARTIFACT_REGISTRY_MOUNT}",
                # Root under which the daemon creates its per-(run, dataloader)
                # host directories. Mounted 1:1 below, so the same path is valid
                # on the host, in the daemon and in the rclone plugin.
                f"{_HOST_VOLUMES_ROOT_FLAG}={self.__host_volumes_root}",
            ]

            if self.__local:
                command.append("--local")

            # Checking if there is already one running
            if self.attach():
                logger.info(
                    f"Daemon is already running (ID: {self.__container.short_id})."
                )
                return

            # Pre-create the host dirs the (root) daemon container needs but
            # must not own: the shared per-workflow-run filesystem (unifs), the
            # per-(run, dataloader) volumes bookkeeping directory and the block
            # registry shard root, so client-side pushes stay possible after
            # the daemon starts.
            self._create_host_volumes()

            dev_dir = os.environ.get("QALL_DEV_DIR")

            volumes = {
                self.__host_block_registry_path: {
                    "bind": _BLOCK_REGISTRY_MOUNT,
                    "mode": "rw",
                },
                self.__host_artifact_registry_path: {
                    "bind": _ARTIFACT_REGISTRY_MOUNT,
                    "mode": "rw",
                },
                "/var/run/docker.sock": {
                    "bind": "/var/run/docker.sock",
                    "mode": "rw",
                },
                "/tmp/qall-secrets": {
                    "bind": "/tmp/qall-secrets",
                    "mode": "rw",
                },
                str(self.__unifs): {
                    "bind": str(self.__unifs),
                    "mode": "rw",
                },
                str(self.__dataloaders): {
                    "bind": str(self.__dataloaders),
                    "mode": "rw",
                },
            }

            # When QALL_DEV_DIR is set, mount the local qall SDK sources into
            # the daemon container (read-only) so the daemon can package them
            # into the runtime image build context instead of installing qall
            # from PyPI. The env var is passed at the exact same path so the
            # daemon can read it without needing to know about host paths.
            if dev_dir:
                volumes[dev_dir] = {"bind": dev_dir, "mode": "ro"}
                logger.info(f"Mounting local qall SDK from {dev_dir} into the daemon.")

            # Start it if not already running
            self.__container = self.__docker_client.containers.run(
                image=self.__image,
                name=self.__container_name,
                command=command,
                detach=True,
                ports=self.__ports,
                environment={"QALL_DEV_DIR": os.environ.get("QALL_DEV_DIR", "")},
                volumes=volumes,
            )
            logger.info(
                f"Daemon started successfully (ID: {self.__container.short_id})."
            )

        except APIError as e:
            raise RuntimeError(f"Error launching the daemon: {e}")

    def register_resource_assignments(self, resource_assigments: dict):
        with self.client as client:
            for task_hash, assignment in resource_assigments.items():
                if not task_hash:
                    raise RuntimeError(
                        "resource assignment must have a target task hash"
                    )

                if not assignment.provider:
                    raise RuntimeError(
                        "resource assignment must have a target provider"
                    )

                resource_name = (
                    assignment.qpu_name
                    or assignment.gpu_name
                    or assignment.cpu_name
                    or ""
                )

                res_entry = client.create_resource_assignment(
                    task_hash=task_hash,
                    resource_provider=assignment.provider,
                    resource_name=resource_name,
                )

                if not res_entry:
                    raise RuntimeError(
                        f"Failed to create resource assignment entry into daemon for task_hash '{task_hash}'"
                    )

    def register_workers(self, worker_definitions: list):
        with self.client as client:
            for wd in worker_definitions:
                if len(wd.input_formats) == 0:
                    raise RuntimeError("worker definition must have one input format")

                if len(wd.input_formats) != 1:
                    raise RuntimeError(
                        "worker definition doesn't support multiple input formats"
                    )

                we = client.create_worker_entry(
                    worker_hash=wd.hash,
                    worker_provider=wd.provider,
                    input_format=wd.input_formats[0],
                )

                if not we:
                    raise RuntimeError("failed to create worker entry into daemon")

    def _ensure_image_exists(self):
        """
        Checks if the image exists on the local host.
        Only triggers a network pull if the image is missing.
        """
        try:
            self.__docker_client.images.get(self.__image)
            logger.debug(
                f"Image {self.__image} is already present locally. Skipped pull."
            )

        except ImageNotFound:
            logger.info(
                f"Image {self.__image} not found locally. Pulling from registry..."
            )
            try:
                self.__docker_client.images.pull(self.__image)
                logger.info("Pull completed successfully.")
            except APIError as e:
                raise RuntimeError(
                    f"Failed to pull image {self.__image}. Check your connection or the image name. Details: {e}"
                )

    # def _wait_for_health(self, timeout: int = 30, interval: float = 0.5):
    #     """
    #     Check the status of the daemon server until it is up and running.
    #     """
    #     logger.info(f"Waiting for daemon availability on port {self.__grpc_port}...")
    #     start_time = time.time()

    #     while time.time() - start_time < timeout:
    #         with self.client as client:
    #             try:
    #                 info = client.get_service_info()
    #                 if info:
    #                     logger.info("Qall daemon gRPC is ready.")
    #                     return True
    #             except:
    #                 pass

    #         time.sleep(interval)

    #     raise TimeoutError("The Qall daemon did not respond within the allocated time.")

    def _create_host_volumes(self):
        # Both dirs are created as the (unprivileged) client user, before the
        # root daemon container starts: the daemon must be able to create
        # children inside them, while cleanup after a run stays possible for
        # the client (a root-owned parent would block that).
        # The mode passed to mkdir() is masked by the process umask, so the
        # 0777 intent is enforced explicitly afterwards.
        for directory in (self.__unifs, self.__dataloaders):
            directory.mkdir(mode=0o777, parents=True, exist_ok=True)
            try:
                os.chmod(directory, 0o777)
            except OSError as e:
                # A leftover root-owned dir from a previous daemon run cannot be
                # chmodded by the unprivileged client; the root daemon can still
                # use it, and it is recreated on the next successful teardown.
                logger.warning(f"Could not relax permissions on {directory}: {e}")

        # Pre-create the block registry shard root as the client user, before
        # the (root) daemon container starts. The daemon's blockstore calls
        # os.MkdirAll(<root>/blocks) on startup; if it creates that dir first it
        # owns it and the unprivileged client's direct task pushes into the
        # shared registry fail with PermissionError. With the dir pre-created
        # (same layout as the client's LocalBlockstore), the daemon's
        # MkdirAll becomes a no-op and client writes stay possible.
        blocks_dir = Path(self.__host_block_registry_path) / "blocks"
        blocks_dir.mkdir(parents=True, exist_ok=True)

    def _teardown_host_volumes(self):
        # Both trees are best-effort: sub-directories under `dataloaders/` are
        # created by the root daemon / rclone plugin (and may hold root-owned
        # FUSE cache entries), so an unprivileged rmtree legitimately fails
        # sometimes. Never let cleanup raise out of a stop().
        for directory in (self.__unifs, self.__dataloaders):
            try:
                shutil.rmtree(directory, ignore_errors=True)
            except OSError as e:
                logger.warning(
                    f"Could not fully remove host volume directory {directory}: {e}"
                )

    def service_info(self) -> bool:
        """
        Check the status of the daemon server
        """
        logger.info(f"Checking for daemon availability on port {self.__grpc_port}...")
        with self.client as client:
            try:
                info = client.get_service_info()
                if info:
                    logger.info("Qall daemon gRPC is ready.")
                    return True
                return False
            except:
                logger.info("Qall daemon gRPC is not running.")
                return False

    def _cleanup_existing_container(self):
        """
        Removes a residual container if it exists.
        """
        try:
            old_container = self.__docker_client.containers.get(self.__container_name)
            old_container.stop(timeout=2)
            old_container.remove()
        except NotFound:
            pass

        self._teardown_host_volumes()
