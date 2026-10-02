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
import os

from typing import Optional
from pathlib import Path

from qall.object import Artifact, DaemonStatus, Daemon, TaskRunStatus
from qall.daemon import DockerDaemonManager

logger = logging.getLogger(__name__)


def start_daemon(
    port: int = 50053,
    image: Optional[str] = None,
    block_registry_path: Optional[str | Path] = None,
    artifact_registry_path: Optional[str | Path] = None,
    worker_provider: Optional[str] = None,
):
    """
    Start a local Qall daemon in a docker container.
    """

    block_registry_path = (
        block_registry_path or Path().home() / ".cache/qall/block-registry"
    )
    artifact_registry_path = (
        artifact_registry_path or Path().home() / ".cache/qall/artifact-registry"
    )
    image = image or "scw/qall-daemon-server:latest"
    worker_provider = worker_provider or "local"

    block_path = Path(block_registry_path).resolve()
    artifact_path = Path(artifact_registry_path).resolve()

    block_path.mkdir(parents=True, exist_ok=True)
    artifact_path.mkdir(parents=True, exist_ok=True)

    daemon_mgr = DockerDaemonManager(
        image=image,
        local=True,
        grpc_port=port,
        host_block_registry_path=str(block_path),
        host_artifact_registry_path=str(artifact_path),
        worker_provider=worker_provider,
    )

    if daemon_mgr.service_info():
        raise RuntimeError(f"Daemon already running locally on port {port}")

    with DockerDaemonManager(
        image=image,
        local=True,
        grpc_port=port,
        host_block_registry_path=str(block_path),
        host_artifact_registry_path=str(artifact_path),
        worker_provider=worker_provider,
    ) as daemon_mgr:

        logs = daemon_mgr.logs()

        logger.info(f"Daemon started on port {port}")

        while logs:
            logger.info(logs.next())


def stop_daemon(
    port: int = 50053,
    image: Optional[str] = None,
):
    """
    Stops an already running local Qall daemon.
    """

    image = image or "scw/qall-daemon-server:latest"

    try:
        daemon_mgr = DockerDaemonManager(
            image=image,
            grpc_port=port,
            local=True,
        )
        if not daemon_mgr.attach():
            logger.warning("No running daemon to stop.")
            return

        daemon_mgr.stop()
        logger.info(f"Daemon stopped on port {port}")

    except Exception as e:
        logger.error(f"Could not stop local daemon.")
        logger.error(f"Daemon address: localhost:{port}")
        logger.error(f"Daemon image: {image})")
        logger.error(f"Reason: {e}")


def restart_daemon(
    port: int = 50053,
    image: Optional[str] = None,
):
    """
    Restarts an already running local Qall daemon.
    """

    image = image or "scw/qall-daemon-server:latest"

    try:
        daemon_mgr = DockerDaemonManager(
            image=image,
            grpc_port=port,
            local=True,
        )
        if not daemon_mgr.attach():
            raise RuntimeError("No active daemon container running.")

        logger.info("Restarting daemon...")
        daemon_mgr.stop()
        logger.info("Daemon stopped...")
        daemon_mgr.start()
        logger.info(f"Daemon restared on port {port}.")

    except Exception as e:
        logger.error(f"Could not restart local daemon.")
        logger.error(f"Daemon address: localhost:{port}")
        logger.error(f"Daemon image: {image})")
        logger.error(f"Reason: {e}")


def get_daemon_status(
    daemon_image: Optional[str] = None,
    daemon_address: Optional[str] = None,
    block_registry: Optional[str] = None,
    artifact_registry: Optional[str] = None,
) -> Daemon:
    """
    Retrieve the status of a daemon instance.
    """
    block_registry = block_registry or Path().home() / ".cache/qall/block-registry"
    artifact_registry = (
        artifact_registry or Path().home() / ".cache/qall/artifact-registry"
    )
    daemon_image = daemon_image or "scw/qall-daemon-server:latest"

    daemon_address = daemon_address or os.getenv(
        "QALL_DAEMON_ADDRESS", "127.0.0.1:50053"
    )
    port = int(daemon_address.split(":")[-1])
    is_local = daemon_address.startswith(("localhost", "127.0.0.1"))
    daemon_mgr = None

    if not is_local:
        logger.warning("Remote daemon execution is not supported yet.")
        return Daemon(status=DaemonStatus.UNKNOWN_STATUS)

    block_registry = Path(block_registry).resolve()
    artifact_registry = Path(artifact_registry).resolve()

    try:
        daemon_mgr = DockerDaemonManager(
            image=daemon_image,
            local=True,
            grpc_port=port,
            host_block_registry_path=str(block_registry),
            host_artifact_registry_path=str(artifact_registry),
        )

        if daemon_mgr.service_info():
            return Daemon(status=DaemonStatus.RUNNING)
        else:
            return Daemon(status=DaemonStatus.STOPPED)
    except Exception as e:
        logger.error(f"Error while checking daemon status: {e}")
        return Daemon(status=DaemonStatus.ERROR)


def run_task(
    task_hash: str,
    input_artifact_hash: Optional[str] = None,
    daemon_address: Optional[str] = None,
    block_registry: Optional[str] = None,
    artifact_registry: Optional[str] = None,
    daemon_image: Optional[str] = None,
    worker_provider: Optional[str] = None,
    timeout: int = 300,
) -> list[Artifact]:
    """
    Orders a local Daemon instance to start and execute a given task.
    """
    block_registry = block_registry or str(Path().home() / ".cache/qall/block-registry")
    artifact_registry = artifact_registry or str(
        Path().home() / ".cache/qall/artifact-registry"
    )
    daemon_image = daemon_image or "scw/qall-daemon-server:latest"

    daemon_address = daemon_address or os.getenv(
        "QALL_DAEMON_ADDRESS", "127.0.0.1:50053"
    )
    port = int(daemon_address.split(":")[-1])
    is_local = daemon_address.startswith(("localhost", "127.0.0.1"))
    daemon_mgr = None

    if not is_local:
        raise RuntimeError(
            "Remote daemon execution is not supported yet. Please use a local daemon."
        )

    # Start a local daemon instance if we cannot reach a running one locally.
    if is_local:
        logger.info(f"Contacting local daemon on port {port}...")
        block_registry = Path(block_registry).resolve()
        artifact_registry = Path(artifact_registry).resolve()

        daemon_mgr = DockerDaemonManager(
            image=daemon_image,
            local=True,
            grpc_port=port,
            host_block_registry_path=str(block_registry),
            host_artifact_registry_path=str(artifact_registry),
            worker_provider=worker_provider,
        )

        if not daemon_mgr.service_info():
            logger.info("Daemon not running, starting it...")
            daemon_mgr.start()

        logger.info(f"Daemon ready at {daemon_address}")

    # Contact daemon to execute given task
    try:
        with daemon_mgr.client as client:

            logger.info(f"Task hash: {task_hash}")
            logger.info(f"Input artifact hash: {input_artifact_hash}")
            logger.info(f"Requesting daemon to execute task at {daemon_address}...")

            info = client.get_service_info()
            logger.info(f"Connected to daemon: {info.name} {info.version}")

            task_run = client.create_task_run(
                task_hash=task_hash,
                artifact_hash=input_artifact_hash,
            )

            logger.info(f"Task run created: {task_run.id}")
            logger.info(f"Waiting for task completion with timeout {timeout}...")

            task_run = client.wait_for_task_run(
                task_run_id=task_run.id,
                timeout=timeout,
                poll_interval=5,
            )

            if task_run.status == TaskRunStatus.DONE:
                return client.list_artifacts(task_run_id=task_run.id)
            elif task_run.status == TaskRunStatus.ERROR:
                raise RuntimeError(f"Task failed with ERROR status: {task_run.status}")
            else:
                raise RuntimeError(
                    f"Task ended with unexpected status: {task_run.status.name}"
                )

    # except Exception as e:
    #     logger.error(f"Could not execute task {task_hash}: {e}")

    finally:
        if daemon_mgr:
            daemon_mgr.stop()
