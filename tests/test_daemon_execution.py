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
Integration tests for daemon-based task execution.

Every task-executing test goes through the shared ``daemon_stack`` fixture
(tests/conftest.py): the daemon provisions a container per task, mounting the
shared per-workflow-run filesystem at /workdir. There is no daemonless/host
execution path — the runtime refuses it (see the /workdir guard in
qall/runtime/subprocessor.py).

Covered:
1. Simple task execution via the daemon
2. Subtask delegation from a parent task container to the daemon
3. Pipeline of dependent tasks through the daemon
4. Artifact flow through daemon execution

Tests are marked ``daemon`` and self-skip when no daemon is available (unless
``-m daemon`` is selected, in which case they fail hard).
"""

import tempfile
import shutil
from pathlib import Path
import pytest

from qall.registry import BlockRegistry
from qall.registry.blockstore import LocalBlockstore
from qall.registry.datastore import LocalDatastore
from qall.runtime import DaemonSubtaskExecutor


@pytest.fixture
def temp_store():
    tmpdir = Path(tempfile.mkdtemp(prefix="qall-test-"))
    # Initialize the local registry structure (blocks dir + datastore lock)
    # so the read-only BlockRegistry used by the executor can open it.
    LocalDatastore(tmpdir).close()
    store = LocalBlockstore(tmpdir)
    yield store, tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


SUB_BASE = """
def double(x):
    return x * 2
"""

MAIN_SRC = """
def double(x):
    result = x * 2
    return result

def process_value(value):
    doubled = double(value)
    return doubled + 10
"""


class TestDaemonExecution:
    """Task execution through a real daemon container."""

    @pytest.mark.daemon
    def test_simple_task_daemon(self, daemon_stack):
        """A simple task runs in a container and its output artifact round-trips."""
        source_code = """
def add(a, b):
    return a + b
"""
        task_hash = daemon_stack.push_task(source_code, "add", entrypoint=True)
        output = daemon_stack.run(task_hash, {"args": (5, 10), "kwargs": {}})
        assert output == 15

    @pytest.mark.daemon
    def test_subtask_delegation_daemon(self, daemon_stack):
        """A parent task container delegates a child call to the daemon.

        The proxy generated inside the parent container submits the child with
        the same workflow run id (QALL_WORKFLOW_RUN_ID is set by the daemon), so
        the child stays on the same /workdir sandbox.
        """
        subtask_hash = daemon_stack.push_task(SUB_BASE, "double")
        main_hash = daemon_stack.push_task(
            MAIN_SRC,
            "process_value",
            entrypoint=True,
            children={"double": subtask_hash},
        )
        output = daemon_stack.run(main_hash, {"args": (5,), "kwargs": {}})
        assert output == 20


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

    def test_daemon_subtask_executor_creation(self, temp_store):
        """Test DaemonSubtaskExecutor instantiation."""
        store, tmpdir = temp_store

        executor = DaemonSubtaskExecutor(
            task_hash="some-task-hash",
            registry=BlockRegistry(tmpdir),
            daemon_address="localhost:50053",
        )

        assert isinstance(executor, DaemonSubtaskExecutor)


class TestWorkflowWithSubtasks:
    """A pipeline of dependent tasks, each executed through the daemon."""

    @pytest.mark.daemon
    def test_pipeline_execution(self, daemon_stack):
        """Each stage is its own daemon run, fed the previous stage's output."""
        add_source = """
def add_five(x):
    return x + 5
"""
        mult_source = """
def multiply_by_three(x):
    return x * 3
"""
        add_hash = daemon_stack.push_task(add_source, "add_five", entrypoint=True)
        mult_hash = daemon_stack.push_task(
            mult_source, "multiply_by_three", entrypoint=True
        )

        first = daemon_stack.run(add_hash, {"args": (10,), "kwargs": {}})
        assert first == 15

        second = daemon_stack.run(mult_hash, {"args": (first,), "kwargs": {}})
        assert second == 45


class TestDaemonIntegration:
    """
    Integration tests against the shared daemon.

    These participate in the ``daemon_integration`` marker so they can also be
    selected explicitly alongside the plain ``daemon`` tasks.
    """

    @pytest.mark.daemon_integration
    def test_daemon_connection(self, daemon_stack):
        """Test connection to the running daemon."""
        from qall_daemon_client import GrpcDaemonClient

        with GrpcDaemonClient(url=daemon_stack.address) as client:
            info = client.get_service_info()
        assert info.name == "qall-daemon"

    @pytest.mark.daemon_integration
    def test_daemon_task_execution(self, daemon_stack):
        """Test task execution via daemon (artifact upload + download)."""
        source_code = """
def multiply(x, y):
    return x * y
"""
        task_hash = daemon_stack.push_task(source_code, "multiply", entrypoint=True)
        output = daemon_stack.run(task_hash, {"args": (6, 7), "kwargs": {}})
        assert output == 42
