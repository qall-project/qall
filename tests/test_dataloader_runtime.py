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
End-to-end tests: a task referencing a dataloader via `@task(dataloaders=[...])`
gets its virtual POSIX mount bound in the local subprocess executor
(TaskRuntimeExecutor), transparently for stdlib I/O APIs.
"""

import cloudpickle
import pytest
import shutil
import tempfile

from pathlib import Path

from qall.core import dataloader as core_dl
from qall.registry import BlockRegistry
from qall.registry.blockstore import LocalBlockstore
from qall.runtime import TaskRuntimeExecutor, LocalArtifactBackend
from qall.object import TaskEnvironment, TaskMetadata, TaskNode, TaskPayload
from qall.codec import DEFAULT_CODEC


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch):
    path = tmp_path / "qall-config.json"
    monkeypatch.setenv("QALL_CONFIG_PATH", str(path))
    return path


@pytest.fixture
def file_src(tmp_path: Path) -> Path:
    src = tmp_path / "storage"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "a.txt").write_text("hello dataloader\n")
    (src / "sub" / "b.csv").write_text("x,y\n1,2\n")
    return src


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


def test_task_with_dataloader(config_path: Path, file_src: Path, blockstore):
    """A task transparently reads/writes through the bound virtual mount."""
    core_dl.add_dataloader("mnist", f"file://{file_src}", "mnist")

    store, tmpdir = blockstore
    source_code = """
def process_dataloader(input):
    import glob
    import os
    from pathlib import Path

    base = "dataloaders/mnist"

    with open(base + "/sub/a.txt") as f:
        first = f.read().strip()

    csv_lines = Path(base + "/sub/b.csv").read_text().strip().splitlines()

    names = sorted(os.listdir(base + "/sub"))

    globbed = sorted(glob.glob(base + "/sub/*.csv"))

    Path(base + "/out.txt").write_text("processed:" + first)

    iterdir = sorted(x.name for x in Path(base + "/sub").iterdir())

    return {
        "first": first,
        "csv": csv_lines,
        "names": names,
        "glob": globbed,
        "wrote": Path(base + "/out.txt").read_text(),
        "iterdir": iterdir,
    }
"""
    task_hash = _push_task(store, source_code, "process_dataloader", ["mnist"])

    artifact_backend = LocalArtifactBackend(
        Path(tempfile.mkdtemp(prefix="dl-art-")) / "a"
    )
    executor = TaskRuntimeExecutor(
        task_hash=task_hash,
        registry=BlockRegistry(tmpdir),
        artifact_backend=artifact_backend,
    )
    result = executor.execute(
        task_run_id="dataloader-run",
        input_artifact=cloudpickle.dumps({"args": (None,), "kwargs": {}}),
    )

    assert result.return_code == 0, result.stderr
    output = cloudpickle.loads(result.output_artifact_bytes)
    assert output["first"] == "hello dataloader"
    assert output["csv"] == ["x,y", "1,2"]
    assert output["names"] == ["a.txt", "b.csv"]
    assert output["glob"] == ["dataloaders/mnist/sub/b.csv"]
    assert output["wrote"] == "processed:hello dataloader"
    assert output["iterdir"] == ["a.txt", "b.csv"]

    # write landed on the object storage (file:// src dir)
    assert (file_src / "out.txt").read_text() == "processed:hello dataloader"


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


def test_task_path_traversal_refused(config_path: Path, file_src: Path, blockstore):
    """A task escaping its mount via `..` must be refused at runtime."""
    core_dl.add_dataloader("mnist", f"file://{file_src}", "mnist")

    store, tmpdir = blockstore
    source_code = """
def malicious(input):
    with open("dataloaders/mnist/../../etc/passwd") as f:
        return f.read()
"""
    task_hash = _push_task(store, source_code, "malicious", ["mnist"])
    executor = TaskRuntimeExecutor(
        task_hash=task_hash,
        registry=BlockRegistry(tmpdir),
    )
    result = executor.execute(
        task_run_id="traversal-run",
        input_artifact=cloudpickle.dumps({"args": (None,), "kwargs": {}}),
    )
    assert result.return_code != 0
    assert "traversal" in result.stderr.lower()


def test_dataloader_dst_traversal_refused_at_bind(
    config_path: Path, file_src: Path, blockstore
):
    """A dataloader whose dst escapes the sandbox is refused at bind time."""
    core_dl.add_dataloader("mnist", f"file://{file_src}", "mnist")

    store, tmpdir = blockstore
    source_code = """
def evil(input):
    return 0
"""
    task_hash = _push_task(store, source_code, "evil", ["mnist"])
    executor = TaskRuntimeExecutor(
        task_hash=task_hash,
        registry=BlockRegistry(tmpdir),
    )

    # Override the persisted dst with a traversal attempt, then execute: the
    # subprocess bind step must refuse it.
    config = core_dl.load_config()
    config["dataloaders"]["mnist"]["dst"] = "../escape"
    core_dl.save_config(config)

    result = executor.execute(
        task_run_id="dst-traversal-run",
        input_artifact=cloudpickle.dumps({"args": (None,), "kwargs": {}}),
    )
    assert result.return_code != 0
    assert "dst" in result.stderr.lower() and "traversal" in result.stderr.lower()
