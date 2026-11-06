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
"""
Shared test fixtures.

``daemon_stack`` (session-scoped): starts a single qall daemon (Docker) and
exposes helpers to push tasks into its block registry and run them over gRPC.

Task execution happens inside daemon-provisioned containers — the shared
per-workflow-run filesystem is mounted at /workdir there — so task-executing
tests must go through this fixture. Host/daemonless execution is not supported
and the runtime refuses it.
"""

import cloudpickle
import importlib.metadata
import shutil
import tempfile
import uuid

from pathlib import Path

import pytest

from qall.codec import DEFAULT_CODEC
from qall.daemon.docker_manager import DockerDaemonManager, _DEFAULT_IMAGE
from qall.object import TaskEnvironment, TaskMetadata, TaskNode, TaskPayload
from qall.registry.blockstore import LocalBlockstore
from qall.registry.datastore import LocalDatastore

DAEMON_ADDRESS = "localhost:50053"
DAEMON_GRPC_PORT = DAEMON_ADDRESS.split(":")[-1]


class DaemonStack:
    """
    One running qall daemon plus the shared block/artifact registries behind it.

    Tasks are content-addressed, so a single session-wide registry is shared by
    all daemon tests: each test pushes its own task blocks and runs them.
    """

    def __init__(self, manager: DockerDaemonManager, registry_dir: Path):
        self.manager = manager
        self.registry_dir = Path(registry_dir)
        self.address = DAEMON_ADDRESS
        self._store = LocalBlockstore(self.registry_dir)

    def push_task(
        self,
        source_code: str,
        task_name: str,
        *,
        entrypoint: bool = False,
        children: dict[str, str] | None = None,
        dataloaders: list[str] | None = None,
    ) -> str:
        """Push a task payload + node into the shared registry; return its hash."""
        store = self._store
        payload = TaskPayload(
            code=source_code,
            code_format="raw",
            environment=TaskEnvironment(image="python:3.13").to_dict(),
            runtime={"qall_version": importlib.metadata.version("qall")},
        )
        payload_block = payload.to_block(DEFAULT_CODEC)
        store.put(payload_block.hash, payload_block.data)

        metadata = TaskMetadata(
            name=task_name,
            entrypoint=entrypoint,
            pure=True,
            dataloaders=dataloaders or [],
        )
        node = TaskNode(
            payload_hash=payload_block.hash,
            children=children or {},
            metadata=metadata.to_dict(),
        )
        node_block = node.to_block(DEFAULT_CODEC)
        store.put(node_block.hash, node_block.data)
        return node_block.hash

    def run(
        self,
        task_hash: str,
        input_data=None,
        *,
        workflow_run_id: str | None = None,
        dataloaders: list[dict] | None = None,
        timeout: float = 120.0,
    ):
        """
        Upload an optional input artifact and run ``task_hash`` via the daemon.

        ``dataloaders`` is a flat list of ``{task_hash, name, src, dst,
        credentials}`` dicts, forwarded on the root ``CreateTaskRun`` request
        (the daemon turns each remote entry into an rclone-backed volume mounted
        at ``/<dst>``).

        Returns the unpickled output value (or ``None`` when the task wrote no
        artifact). Raises ``AssertionError`` when the run does not complete.
        """
        from qall_daemon_client import GrpcDaemonClient, TaskRunStatus
        from qall_daemon_client.v1.objects import DataloaderEntry

        workflow_run_id = workflow_run_id or str(uuid.uuid4())

        with GrpcDaemonClient(url=self.address) as client:
            artifact_hash = None
            if input_data is not None:
                artifact = client.create_artifact(
                    task_run_id=workflow_run_id,
                    payload=cloudpickle.dumps(input_data),
                )
                artifact_hash = artifact.hash

            task_run = client.create_task_run(
                task_hash=task_hash,
                workflow_run_id=workflow_run_id,
                artifact_hash=artifact_hash,
                dataloaders=[DataloaderEntry(**entry) for entry in (dataloaders or [])],
            )

            completed = client.wait_for_task_run(
                task_run_id=task_run.id,
                timeout=timeout,
            )
            if completed.status != TaskRunStatus.DONE:
                raise AssertionError(
                    f"Task run {task_run.id} ended with status {completed.status}"
                )

            artifacts = client.list_artifacts(task_run_id=task_run.id)
            if not artifacts:
                return None
            return cloudpickle.loads(client.download_artifact(artifacts[-1].hash))


def _expect_daemon_tests(config) -> bool:
    """True when a ``daemon``/``daemon_integration`` marker is explicitly selected."""
    markexpr = config.getoption("markexpr") or ""
    return "daemon" in markexpr


def _safe_rmtree(path: Path) -> None:
    """
    Best-effort removal of a dir that may contain files written as root by the
    daemon container; falls back to a throwaway root container sweep.
    """
    try:
        shutil.rmtree(path)
        return
    except Exception:
        pass
    try:
        from docker import from_env

        parent = path.parent
        from_env().containers.run(
            image=_DEFAULT_IMAGE,
            entrypoint=["/bin/sh", "-c", f"rm -rf '/clean/{path.name}'"],
            volumes={str(parent): {"bind": "/clean", "mode": "rw"}},
            remove=True,
        )
    except Exception:
        pass


@pytest.fixture(scope="session")
def daemon_stack(request) -> DaemonStack:
    registry_dir = Path(tempfile.mkdtemp(prefix="qall-daemon-session-"))
    LocalDatastore(registry_dir).close()

    # Pre-create the block registry's shard root as the current user, BEFORE
    # the daemon starts. The dockerized daemon runs as root and its blockstore
    # starts up with os.MkdirAll(<root>/blocks) — if it creates the dir first it
    # owns it, and the client's push_task writes (shard dirs + block files)
    # then fail with PermissionError. Pre-creating it keeps every object below
    # the shared registry client-owned; the daemon's MkdirAll becomes a no-op.
    (registry_dir / "blocks").mkdir(parents=True, exist_ok=True)

    manager = DockerDaemonManager(
        grpc_port=DAEMON_GRPC_PORT,
        host_block_registry_path=str(registry_dir),
        host_artifact_registry_path=str(registry_dir / "artifacts"),
    )

    try:
        manager.start()
    except Exception as exc:
        _safe_rmtree(registry_dir)
        if _expect_daemon_tests(request.config):
            raise RuntimeError(
                "Daemon-stack tests were explicitly selected (-m daemon) but "
                f"the daemon could not be started: {exc}"
            ) from exc
        pytest.skip(f"Daemon not available; skipping daemon tests: {exc}")

    stack = DaemonStack(manager=manager, registry_dir=registry_dir)

    yield stack

    try:
        manager.stop()
    except Exception:
        pass
    finally:
        _safe_rmtree(registry_dir)
