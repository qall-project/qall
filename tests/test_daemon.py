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
import socket
import tempfile
from pathlib import Path

import pytest
import requests

from qall.core.daemon import DockerDaemonManager


@pytest.fixture
def create_daemon_registry_paths():
    with (
        tempfile.TemporaryDirectory() as artifacts_dir,
        tempfile.TemporaryDirectory() as blocks_dir,
    ):
        artifacts_path = Path(artifacts_dir)
        blocks_path = Path(blocks_dir)
        (blocks_path / "blocks").mkdir(parents=True, exist_ok=True)
        yield artifacts_path, blocks_path


def test_daemon_grpc_and_http_connections(create_daemon_registry_paths):
    """
    Test DockerDaemonManager's lifecycle and validate that
    the gRPC (TCP) and HTTP (REST Gateway) ports are open and accessible.
    """

    grpc_port = 50053
    http_port = 8080

    artifacts_path, blocks_path = create_daemon_registry_paths

    print("===test_daemon_grpc_and_http_connections===")
    manager = DockerDaemonManager(
        image="scw/qall-daemon-server:latest",
        grpc_port=grpc_port,
        http_port=http_port,
        host_block_registry_path=str(blocks_path),
        host_artifact_registry_path=str(artifacts_path),
    )

    with manager as daemon:
        assert daemon.container is not None
        assert (
            daemon.container.status == "created" or daemon.container.status == "running"
        )

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            result = sock.connect_ex(("localhost", grpc_port))
            assert result == 0

        try:
            response = requests.get(f"http://localhost:{http_port}/v1", timeout=5)

            assert (
                response.status_code == 200
            ), f"HTTP gateway returned an error: {response.status_code}."

            payload = response.json()
            assert (
                "name" in payload or "version" in payload
            ), "Incorrect HTTP response (DaemonInfo)."

        except requests.exceptions.RequestException as e:
            logs = daemon.container.logs().decode("utf-8")
            pytest.fail(
                f"Unable to connect to HTTP gateway on port {http_port}.\n"
                f"Details : {e}\n"
                f"=== Daemon container logs ===\n{logs}"
            )
