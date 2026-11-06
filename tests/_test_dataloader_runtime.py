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
Dataloader validation (unit-level).

End-to-end dataloader *execution* is exercised through the daemon stack
(see test_dataloader_daemon.py::TestDataloaderDaemonIntegration); the v2
dataloader rewrite owns the remaining execution surface. The tests here only
cover failure modes detected before task execution starts (no container, no
/workdir). In particular a task referencing a dataloader with no provisioned
secrets must fail loudly instead of reaching the runtime.
"""

import cloudpickle
import pytest
import shutil

from pathlib import Path

from qall.registry import BlockRegistry
from qall.registry.blockstore import LocalBlockstore
from qall.runtime import TaskRuntimeExecutor
from qall.object import TaskEnvironment, TaskMetadata, TaskNode, TaskPayload
from qall.codec import DEFAULT_CODEC


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch):
    path = tmp_path / "qall-config.yml"
    monkeypatch.setenv("QALL_CONFIG_PATH", str(path))
    return path


@pytest.fixture
def blockstore(tmp_path: Path) -> tuple[LocalBlockstore, Path]:
    store = LocalBlockstore(tmp_path)
    yield store, tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)


def _push_task(
    store: LocalBlockstore,
    source_code: str,
    task_name: str,
    dataloaders: list[str] | None = None,
) -> str:
    payload = TaskPayload(
        code=source_code,
        code_format="raw",
        environment=TaskEnvironment(image="python:3.13").to_dict(),
    )
    payload_block = payload.to_block(DEFAULT_CODEC)
    payload_hash = payload_block.hash
    store.put(payload_hash, payload_block.data)

    metadata = TaskMetadata(
        name=task_name, entrypoint=True, pure=True, dataloaders=dataloaders or []
    )
    node = TaskNode(
        payload_hash=payload_hash,
        children={},
        metadata=metadata.to_dict(),
    )
    node_block = node.to_block(DEFAULT_CODEC)
    store.put(node_block.hash, node_block.data)
    return node_block.hash


def test_task_with_undefined_dataloader_fails(config_path: Path, blockstore):
    store, tmpdir = blockstore
    source_code = """
def ghost(input):
    return 0
"""
    task_hash = _push_task(store, source_code, "ghost", ["not-defined"])
    executor = TaskRuntimeExecutor(
        task_hash=task_hash,
        registry=BlockRegistry(tmpdir),
    )
    with pytest.raises(ValueError, match="no such dataloader"):
        executor.execute(
            task_run_id="ghost-run",
            input_artifact=cloudpickle.dumps({"args": (None,), "kwargs": {}}),
        )
