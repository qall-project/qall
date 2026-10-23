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

import abc
import logging
import time

from typing import Iterator, Optional

from qall_daemon_client import GrpcDaemonClient

logger = logging.getLogger(__name__)


class BaseDaemonManager(abc.ABC):
    """
    Common contract implemented by every daemon backend (Docker, systemd, ...).
    """

    grpc_port: int

    @property
    def client(self) -> GrpcDaemonClient:
        """
        Instantiate (and cache) the gRPC client for this daemon.
        """
        if getattr(self, "_client", None) is None:
            addr = "localhost"
            self._client = GrpcDaemonClient(url=f"{addr}:{self.grpc_port}")
        return self._client

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self.stop()

    def start(self) -> "BaseDaemonManager":
        self._start_daemon()
        self._wait_for_health()

        return self

    def service_info(self) -> bool:
        """
        Check the status of the daemon server.
        """
        logger.info(f"Checking for daemon availability on port {self.grpc_port}...")
        with self.client as client:
            try:
                info = client.get_service_info()
                if info:
                    logger.info("Qall daemon gRPC is ready.")
                    return True
                return False
            except Exception:
                logger.info("Qall daemon gRPC is not running.")
                return False

    def _wait_for_health(self, timeout: int = 30, interval: float = 0.5) -> bool:
        """
        Poll the daemon gRPC endpoint until it is up and running.
        """
        logger.info(f"Waiting for daemon availability on port {self.grpc_port}...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            with self.client as client:
                try:
                    info = client.get_service_info()
                    if info:
                        logger.info("Qall daemon gRPC is ready.")
                        return True
                except Exception:
                    pass

            time.sleep(interval)

        raise TimeoutError("The Qall daemon did not respond within the allocated time.")

    def register_resource_assignments(self, resource_assigments: dict):
        """
        Register resource assignments into the daemon.
        """
        with self.client as client:
            for task_hash, assignment in resource_assigments.items():
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
        """
        Register worker definitions into the daemon.
        """
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

    # --- backend-specific lifecycle -----------------------------------------

    @abc.abstractmethod
    def _start_daemon(self) -> None:
        """Start the daemon using a specific backend (container, systemd unit, ...)."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Stop the daemon and clean up its resources."""

    @abc.abstractmethod
    def logs(self) -> Optional[Iterator[str]]:
        """
        Return an iterator over the daemon log lines.
        """

    @abc.abstractmethod
    def is_running(self) -> bool:
        """Return True when a daemon instance is running and manageable."""