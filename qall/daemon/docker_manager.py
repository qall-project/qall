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
import docker
import time

from pathlib import Path
from typing import Optional

from docker.errors import DockerException, APIError, ImageNotFound, NotFound
from docker.models.containers import Container

from qall_daemon_client import GrpcDaemonClient

from .base_manager import BaseDaemonManager

logger = logging.getLogger(__name__)

__DEFAULT_IMAGE = "rg.fr-par.scw.cloud/qall-project/qall-daemon:latest"


class DockerDaemonManager(BaseDaemonManager):
    """
    Manages the lifecycle of the local Qall Daemon via Docker.
    """

    def __init__(
        self,
        grpc_port: int = 50053,
        http_port: int = 8080,
        local: bool = True,
        host_block_registry_path: str | Path = Path().home()
        / ".cache/qall/block-registry",
        host_artifact_registry_path: str | Path = Path().home()
        / ".cache/qall/artifact-registry",
        worker_provider: Optional[str] = None,
    ):
        self.__image = __DEFAULT_IMAGE
        self.__container_name = "qalld"
        self.__grpc_port = grpc_port
        self.__http_port = http_port
        self.__ports = {"50053/tcp": self.__grpc_port, "8080/tcp": self.__http_port}
        self.__local = local
        self.__host_block_registry_path = str(host_block_registry_path)
        self.__host_artifact_registry_path = str(host_artifact_registry_path)

        try:
            self.__docker_client = docker.from_env()
        except DockerException as e:
            raise RuntimeError(
                "Docker does not seem to be running or accessible on this machine."
            ) from e

        self.__container = None
        self.__client = None

    @property
    def client(self) -> GrpcDaemonClient:
        if not self.__client:
            addr = "localhost"

            # Uncomment to allow connection from remote and not local-only (needs the local attribute implementation)
            # if not self.local:
            #     addr = "0.0.0.0"

            self.__client = GrpcDaemonClient(url=f"{addr}:{self.__grpc_port}")
        return self.__client

    @property
    def container(self) -> Container | None:
        return self.__container

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self.stop()

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

    def start(self):
        self._start_daemon()
        self._wait_for_health()

        return self

    def stop(self):
        """
        Stop and cleanup the daemon container.
        """
        if self.__container:
            logger.info("Stopping and cleaning up the Qall Daemon...")
            try:
                self.__container.stop(timeout=5)
                self.__container.remove()
                logger.info("Cleanup complete.")
            except APIError as e:
                logger.warning(f"Failed to cleanly remove the container: {e}")
            return

    def logs(self):
        """
        Stream the logs of the daemon container.
        """
        if self.__container:
            try:
                return self.__container.logs(stream=True)
            except APIError as e:
                logger.error(f"Failed to retrieve logs: {e}")

    def _start_daemon(self):
        """
        Creates and start a container with our local daemon server.
        """
        logger.info(f"Starting Qall daemon (from {self.__image})...")

        self._cleanup_existing_container()
        self._ensure_image_exists()

        try:
            command = [f"--host-task-dir={self.__host_block_registry_path}"]

            if self.__worker_provider:
                command.append(f"--worker-provider={self.__worker_provider}")

            if self.__local:
                command.append("--local")

            # Checking if there is already one running
            if self.attach():
                logger.info(
                    f"Daemon is already running (ID: {self.__container.short_id})."
                )
                return

            # Start it if not already running
            self.__container = self.__docker_client.containers.run(
                image=self.__image,
                name=self.__container_name,
                command=command,
                detach=True,
                ports=self.__ports,
                volumes={
                    self.__host_block_registry_path: {
                        "bind": "/block-registry",
                        "mode": "rw",
                    },
                    self.__host_artifact_registry_path: {
                        "bind": "/artifact-registry",
                        "mode": "rw",
                    },
                    "/var/run/docker.sock": {
                        "bind": "/var/run/docker.sock",
                        "mode": "rw",
                    },
                    "/dev/shm/qall-secrets": {
                        "bind": "/dev/shm/qall-secrets",
                        "mode": "rw",
                    },
                },
            )
            logger.info(
                f"Daemon started successfully (ID: {self.__container.short_id})."
            )

        except APIError as e:
            raise RuntimeError(f"Error launching the daemon: {e}")

    def register_resource_assignments(self, resource_asigments: dict):
        with self.client as client:
            for hash, res_assignement in resource_asigments:
                pass

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

    def _wait_for_health(self, timeout: int = 30, interval: float = 0.5):
        """
        Check the status of the daemon server until it is up and running.
        """
        logger.info(f"Waiting for daemon availability on port {self.__grpc_port}...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            with self.client as client:
                try:
                    info = client.get_service_info()
                    if info:
                        logger.info("Qall daemon gRPC is ready.")
                        return True
                except:
                    pass

            time.sleep(interval)

        raise TimeoutError("The Qall daemon did not respond within the allocated time.")

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
