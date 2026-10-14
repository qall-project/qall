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
Runtime proxy reconstruction for async child tasks.

Whether a child task's runtime proxy is generated as ``async def`` must follow
the child's own definition, not how the parent happens to call it (``await``,
``asyncio.TaskGroup``/``create_task``, ``asyncio.gather``, ...). These tests
exercise the helper that inspects the child's stored payload source and the
source emitted by ``TaskRuntimeExecutor`` without requiring a running daemon.
"""

import tempfile
import shutil
import threading
from pathlib import Path

import pytest

from qall.object import TaskMetadata, TaskEnvironment, TaskNode, TaskPayload
from qall.registry import BlockRegistry
from qall.registry.blockstore import LocalBlockstore
from qall.registry.datastore import LocalDatastore
from qall.codec import DEFAULT_CODEC
from qall.runtime import TaskRuntimeExecutor, LocalArtifactBackend
from qall.runtime.task_executor import _child_task_is_async


@pytest.fixture
def temp_store():
    tmpdir = Path(tempfile.mkdtemp(prefix="qall-test-"))
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


def _registry(tmpdir: Path) -> BlockRegistry:
    return BlockRegistry(tmpdir)


class TestChildTaskIsAsync:
    """Ground-truth detection from the child's own stored source."""

    def test_async_child(self, temp_store):
        store, tmpdir = temp_store
        child_hash, _ = _push_task(
            store,
            """
async def watcher(dir, timeout):
    return dir
""",
            "watcher",
        )
        assert _child_task_is_async(_registry(tmpdir), child_hash, "watcher") is True

    def test_sync_child(self, temp_store):
        store, tmpdir = temp_store
        child_hash, _ = _push_task(
            store,
            """
def double(x):
    return x * 2
""",
            "double",
        )
        assert _child_task_is_async(_registry(tmpdir), child_hash, "double") is False

    def test_missing_block_raises(self, temp_store):
        _, tmpdir = temp_store
        with pytest.raises(
            RuntimeError, match="Unable to determine whether child task"
        ):
            _child_task_is_async(_registry(tmpdir), "deadbeef", "ghost")

    def test_no_matching_definition_raises(self, temp_store):
        store, tmpdir = temp_store
        child_hash, _ = _push_task(
            store,
            """
def other(x):
    return x
""",
            "other",
        )
        with pytest.raises(
            RuntimeError, match="does not define a function named 'double'"
        ):
            _child_task_is_async(_registry(tmpdir), child_hash, "double")

    def test_ambiguous_definitions_raise(self, temp_store):
        store, tmpdir = temp_store
        child_hash, _ = _push_task(
            store,
            """
def double(x):
    return x

def double(x, y=0):
    return x + y
""",
            "double",
        )
        with pytest.raises(RuntimeError, match="multiple definitions of 'double'"):
            _child_task_is_async(_registry(tmpdir), child_hash, "double")


class TestAsyncProxyReconstruction:
    """The emitted runtime source must match the child's async-ness."""

    def _built_source(
        self,
        store: LocalBlockstore,
        tmpdir: Path,
        parent_source: str,
        children: dict[str, str],
        monkeypatch,
    ) -> str:
        parent_hash, _ = _push_task(
            store,
            parent_source,
            "main",
            entrypoint=True,
            children=children,
        )
        artifact_backend = LocalArtifactBackend(tmpdir / "artifacts")
        executor = TaskRuntimeExecutor(
            task_hash=parent_hash,
            registry=tmpdir,
            artifact_backend=artifact_backend,
        )

        captured = {}

        def fake_run_task_in_subprocess(**kwargs):
            captured["source_code"] = kwargs["source_code"]
            return {
                "return_code": 0,
                "return_value": None,
                "stdout": "",
                "stderr": "",
            }

        monkeypatch.setattr(
            "qall.runtime.task_executor.run_task_in_subprocess",
            fake_run_task_in_subprocess,
        )

        executor.execute(task_run_id="async-proxy-run")
        return captured["source_code"]

    def test_task_group_create_task(self, temp_store, temp_artifacts, monkeypatch):
        """Async children scheduled via TaskGroup().create_task() stay async."""
        store, tmpdir = temp_store

        watchdog_hash, _ = _push_task(
            store,
            """
async def file_watchdog(dir, timeout):
    return dir
""",
            "file_watchdog",
        )
        fsio_hash, _ = _push_task(
            store,
            """
async def rand_fsio(dir, timeout):
    return dir
""",
            "rand_fsio",
        )

        parent_source = """
import asyncio

async def main():
    async with asyncio.TaskGroup() as tg:
        tg.create_task(file_watchdog(".", 1))
        tg.create_task(rand_fsio(".", 1))
    return 0
"""
        source = self._built_source(
            store,
            tmpdir,
            parent_source,
            {"file_watchdog": watchdog_hash, "rand_fsio": fsio_hash},
            monkeypatch,
        )

        assert "async def file_watchdog(*args, **kwargs):" in source
        assert "async def rand_fsio(*args, **kwargs):" in source

    def test_gather(self, temp_store, temp_artifacts, monkeypatch):
        """Async children passed to asyncio.gather() stay async."""
        store, tmpdir = temp_store

        watchdog_hash, _ = _push_task(
            store,
            """
async def file_watchdog(dir, timeout):
    return dir
""",
            "file_watchdog",
        )
        fsio_hash, _ = _push_task(
            store,
            """
async def rand_fsio(dir, timeout):
    return dir
""",
            "rand_fsio",
        )

        parent_source = """
import asyncio

async def main():
    await asyncio.gather(file_watchdog(".", 1), rand_fsio(".", 1))
    return 0
"""
        source = self._built_source(
            store,
            tmpdir,
            parent_source,
            {"file_watchdog": watchdog_hash, "rand_fsio": fsio_hash},
            monkeypatch,
        )

        assert "async def file_watchdog(*args, **kwargs):" in source
        assert "async def rand_fsio(*args, **kwargs):" in source

    def test_sync_child_kept_sync(self, temp_store, temp_artifacts, monkeypatch):
        """A plain def child still gets a synchronous proxy."""
        store, tmpdir = temp_store

        double_hash, _ = _push_task(
            store,
            """
def double(x):
    return x * 2
""",
            "double",
        )

        parent_source = """
def main():
    return double(21)
"""
        source = self._built_source(
            store,
            tmpdir,
            parent_source,
            {"double": double_hash},
            monkeypatch,
        )

        assert "def double(*args, **kwargs):" in source
        assert "async def double(*args, **kwargs):" not in source


class TestConcurrentRegistrySharing:
    """LMDB environments must be shared across concurrently-running tasks."""

    def test_concurrent_registries_same_path(self, temp_store):
        """Two BlockRegistry instances on the same path, opened concurrently as
        child task proxies do (asyncio.to_thread), must share the LMDB env
        instead of failing with 'environment ... is already open'."""
        store, tmpdir = temp_store
        task_hash, _ = _push_task(
            store,
            """
def child():
    return 1
""",
            "child",
        )

        opened = []
        errors = []

        def open_readonly():
            try:
                opened.append(BlockRegistry(tmpdir, read_only=True))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=open_readonly) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, errors
        assert len(opened) == 2

        # Closing one holder must not invalidate the other.
        opened[0].close()
        node = opened[1].get_node_from_local(hash=task_hash)
        assert node is not None

    def test_datastore_close_refcount(self, temp_store):
        """LocalDatastore close() is reference counted: the LMDB env survives
        until its last holder releases it, and a later open re-creates it."""
        store, tmpdir = temp_store

        ds1 = LocalDatastore(tmpdir)
        ds2 = LocalDatastore(tmpdir)

        ds1.close()
        # ds2 still owns the shared env and stays usable.
        assert ds2.resolve_tag("whatever", "latest") == (None, False)

        ds2.close()
        # A fresh datastore re-opens cleanly once the pool entry was released.
        ds3 = LocalDatastore(tmpdir)
        ds3.close()
