# Copyright 2026 Scaleway
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Integration tests for daemon-based task execution.

Tests cover:
1. Local (daemonless) execution mode
2. Daemon-based execution mode (requires running daemon)
3. Subtask delegation from parent task to daemon
4. Artifact flow through daemon execution
"""

import tempfile
import shutil
from pathlib import Path
import pytest
import cloudpickle

from qall.core.runtime import ExecutionMode
from qall.object import TaskEnvironment, TaskMetadata, TaskNode, TaskPayload
from qall.daemon.docker_manager import DockerDaemonManager
from qall.registry import BlockRegistry
from qall.registry.blockstore import LocalBlockstore
from qall.registry.datastore import LocalDatastore
from qall.codec import DEFAULT_CODEC
from qall.runtime import (
    TaskRuntimeExecutor,
    LocalArtifactBackend,
    LocalSubtaskExecutor,
    DaemonSubtaskExecutor,
)


@pytest.fixture
def temp_store():
    tmpdir = Path(tempfile.mkdtemp(prefix="qall-test-"))
    # Initialize the local registry structure (blocks dir + datastore lock)
    # so the read-only BlockRegistry used by the executor can open it.
    LocalDatastore(tmpdir).close()
    store = LocalBlockstore(tmpdir)
    yield store, tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def temp_artifacts():
    tmpdir = Path(tempfile.mkdtemp(prefix="qall-artifacts-"))
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


def _push_task(
    store: LocalBlockstore,
    source_code: str,
    task_name: str,
    entrypoint: bool = False,
    children: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Push a task payload + node into the local store.

    Returns the (task_hash, payload_hash) tuple.
    """
    payload = TaskPayload(
        code=source_code,
        code_format="raw",
        environment=TaskEnvironment(image="python:3.13").to_dict(),
    )
    payload_block = payload.to_block(DEFAULT_CODEC)
    payload_hash = payload_block.hash
    store.put(payload_hash, payload_block.data)

    metadata = TaskMetadata(name=task_name, entrypoint=entrypoint, pure=True)
    node = TaskNode(
        payload_hash=payload_hash,
        children=children or {},
        metadata=metadata.to_dict(),
    )
    node_block = node.to_block(DEFAULT_CODEC)
    task_hash = node_block.hash
    store.put(task_hash, node_block.data)

    return task_hash, payload_hash


class TestLocalExecutionMode:
    """Tests for local (daemonless) execution mode."""

    def test_simple_task_local(self, temp_store, temp_artifacts):
        """Test simple task execution in local mode."""
        store, tmpdir = temp_store
        artifact_backend = LocalArtifactBackend(temp_artifacts)

        source_code = """
def add(a, b):
    return a + b
"""
        task_hash, _ = _push_task(store, source_code, "add", entrypoint=True)

        executor = TaskRuntimeExecutor(
            task_hash=task_hash,
            registry=tmpdir,
            artifact_backend=artifact_backend,
        )

        input_data = cloudpickle.dumps({"args": (5, 10), "kwargs": {}})
        result = executor.execute(task_run_id="local-run", input_artifact=input_data)

        assert result.return_code == 0
        assert result.output_artifact_bytes is not None
        output_value = cloudpickle.loads(result.output_artifact_bytes)
        assert output_value == 15

    def test_task_with_subtask_local(self, temp_store, temp_artifacts):
        """Test subtask delegation in local mode.

        The TaskRuntimeExecutor delegates subtask calls to the daemon through
        generated proxy functions. For daemon-less runs, LocalSubtaskExecutor
        executes the child task with a fresh TaskRuntimeExecutor so the delegation
        logic can be exercised without a running daemon.
        """
        store, tmpdir = temp_store
        artifact_backend = LocalArtifactBackend(temp_artifacts)

        subtask_source = """
def double(x):
    return x * 2
"""
        subtask_hash, _ = _push_task(store, subtask_source, "double")

        executor = LocalSubtaskExecutor(
            task_hash=subtask_hash,
            registry=BlockRegistry(tmpdir),
            artifact_backend=artifact_backend,
        )

        result = executor.execute_subtask(
            parent_task_run_id="parent-run",
            input_data={"args": (5,), "kwargs": {}},
        )

        assert result.return_code == 0
        assert result.output_artifact_bytes is not None
        output_value = cloudpickle.loads(result.output_artifact_bytes)
        assert output_value == 10


class TestDaemonClientWrapper:
    """Tests for the daemon client wrapper."""

    def test_daemon_client_import(self):
        """Test that daemon client can be imported."""
        from qall_daemon_client import (
            DaemonClient,
            GrpcDaemonClient,
            TaskRun,
            TaskRunStatus,
        )

        assert DaemonClient is not None
        assert GrpcDaemonClient is not None
        assert TaskRun is not None
        assert TaskRunStatus is not None

    def test_daemon_client_creation(self):
        """Test daemon client instantiation."""
        from qall_daemon_client import DaemonClient, GrpcDaemonClient

        client = GrpcDaemonClient(url="localhost:50053")
        assert isinstance(client, DaemonClient)

    def test_daemon_client_context_manager(self):
        """Test daemon client context manager (without connection)."""
        from qall_daemon_client import GrpcDaemonClient

        with GrpcDaemonClient(url="localhost:50053") as client:
            assert isinstance(client, GrpcDaemonClient)


class TestSubtaskExecutor:
    """Tests for subtask executor abstractions."""

    def test_local_subtask_executor_creation(self, temp_store, temp_artifacts):
        """Test LocalSubtaskExecutor instantiation."""
        store, tmpdir = temp_store
        artifact_backend = LocalArtifactBackend(temp_artifacts)

        executor = LocalSubtaskExecutor(
            task_hash="some-task-hash",
            registry=BlockRegistry(tmpdir),
            artifact_backend=artifact_backend,
        )

        assert isinstance(executor, LocalSubtaskExecutor)

    def test_daemon_subtask_executor_creation(self, temp_store):
        """Test DaemonSubtaskExecutor instantiation."""
        store, tmpdir = temp_store

        executor = DaemonSubtaskExecutor(
            task_hash="some-task-hash",
            registry=BlockRegistry(tmpdir),
            daemon_address="localhost:50053",
        )

        assert isinstance(executor, DaemonSubtaskExecutor)


class TestExecutionMode:
    """Tests for execution mode configuration."""

    def test_execution_mode_enum(self):
        """Test ExecutionMode enum values."""
        assert ExecutionMode.LOCAL.value == "local"
        assert ExecutionMode.DAEMON.value == "daemon"

    def test_execution_mode_from_string(self):
        """Test creating ExecutionMode from string."""
        assert ExecutionMode("local") == ExecutionMode.LOCAL
        assert ExecutionMode("daemon") == ExecutionMode.DAEMON

    def test_execution_mode_invalid(self):
        """Test invalid execution mode raises error."""
        with pytest.raises(ValueError):
            ExecutionMode("invalid")


class TestDaemonIntegration:
    """
    Integration tests requiring a running daemon.

    These tests are marked to be skipped by default and can be run with:
    pytest -m daemon_integration
    """

    @pytest.fixture
    def daemon_address(self):
        return "localhost:50053"

    def test_daemon_connection(self, daemon_address):
        """Test connection to running daemon."""
        from qall_daemon_client import GrpcDaemonClient

        manager = DockerDaemonManager(
            image="scw/qall-daemon-server:latest",
            grpc_port=daemon_address.split(":")[-1],
        )
        try:
            with manager as daemon:
                with GrpcDaemonClient(url=daemon_address) as client:
                    info = client.get_service_info()
        except Exception as e:
            pytest.skip(f"Daemon not available: {e}")
        assert info.name == "qall-daemon"

    def test_daemon_task_execution(
        self, daemon_address, temp_store: tuple[LocalBlockstore, Path]
    ):
        """Test task execution via daemon."""
        from qall_daemon_client import GrpcDaemonClient, TaskRunStatus

        store, tmpdir = temp_store

        source_code = """
def multiply(x, y):
    return x * y
"""
        task_hash, _ = _push_task(store, source_code, "multiply", entrypoint=True)

        manager = DockerDaemonManager(
            image="scw/qall-daemon-server:latest",
            grpc_port=daemon_address.split(":")[-1],
            host_block_registry_path=str(tmpdir),
            host_artifact_registry_path=str(tmpdir / "artifacts"),
        )

        with manager as daemon:
            with GrpcDaemonClient(url=daemon_address) as client:

                try:
                    client.get_service_info()
                except Exception as e:
                    pytest.skip(f"Daemon not available: {e}")

                input_data = cloudpickle.dumps({"args": (6, 7), "kwargs": {}})
                artifact = client.create_artifact(
                    task_run_id="integration-input",
                    payload=input_data,
                )

                task_run = client.create_task_run(
                    task_hash=task_hash,
                    artifact_hash=artifact.hash,
                )

                completed = client.wait_for_task_run(
                    task_run_id=task_run.id,
                    timeout=60.0,
                )

                assert completed.status == TaskRunStatus.DONE

                artifacts = client.list_artifacts(task_run_id=task_run.id)
                assert len(artifacts) > 0

                output_bytes = client.download_artifact(artifacts[-1].hash)
                output_value = cloudpickle.loads(output_bytes)
                assert output_value == 42


class TestWorkflowWithSubtasks:
    """Test a pipeline of dependent tasks executed locally."""

    def test_pipeline_execution(self, temp_store, temp_artifacts):
        """Test a simple pipeline (add_five -> multiply_by_three).

        Each stage is executed as an independent task in local mode, feeding
        its output artifact into the next stage.
        """
        store, tmpdir = temp_store
        artifact_backend = LocalArtifactBackend(temp_artifacts)

        add_source = """
def add_five(x):
    return x + 5
"""
        mult_source = """
def multiply_by_three(x):
    return x * 3
"""
        add_hash, _ = _push_task(store, add_source, "add_five", entrypoint=True)
        mult_hash, _ = _push_task(
            store, mult_source, "multiply_by_three", entrypoint=True
        )

        registry = BlockRegistry(tmpdir)

        executor = TaskRuntimeExecutor(
            task_hash=add_hash,
            registry=registry,
            artifact_backend=artifact_backend,
        )
        first_input = cloudpickle.dumps({"args": (10,), "kwargs": {}})
        first_result = executor.execute(
            task_run_id="pipeline-stage-1", input_artifact=first_input
        )
        assert first_result.return_code == 0
        first_output = cloudpickle.loads(first_result.output_artifact_bytes)
        assert first_output == 15

        executor = TaskRuntimeExecutor(
            task_hash=mult_hash,
            registry=registry,
            artifact_backend=artifact_backend,
        )
        second_input = cloudpickle.dumps({"args": (first_output,), "kwargs": {}})
        second_result = executor.execute(
            task_run_id="pipeline-stage-2", input_artifact=second_input
        )
        assert second_result.return_code == 0
        second_output = cloudpickle.loads(second_result.output_artifact_bytes)
        assert second_output == 45
