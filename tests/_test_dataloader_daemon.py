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
Dataloader provisioning (client-side, unit-level).

The end-to-end dataloader execution path is being rewritten for dataloader v2;
the tests kept here cover the client-side provisioning contract that v2 will
port:

  1. Provisioning of `/tmp/qall-dataloaders/<hash>.json` from a pushed
     workflow DAG (dir 0700, files 0400, resolved creds).
  2. A task referencing a dataloader with no provisioned secrets fails loudly
     before any task execution starts (no container / no /workdir involved).
"""

import cloudpickle
import json
import shutil
import importlib.metadata

from pathlib import Path

import pytest

from qall.core import dataloader as core_dl
from qall.config import dataloader as config_dl
from qall.registry import BlockRegistry
from qall.registry.blockstore import LocalBlockstore
from qall.runtime import TaskRuntimeExecutor
from qall.object import (
    TaskEnvironment,
    TaskMetadata,
    TaskNode,
    TaskPayload,
    TaskDag,
)
from qall.codec import DEFAULT_CODEC
from qall.credential import credentials as credential_module


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch):
    path = tmp_path / "qall-config.yml"
    monkeypatch.setenv("QALL_CONFIG_PATH", str(path))
    return path


@pytest.fixture
def secrets_dir(tmp_path: Path, monkeypatch):
    """Isolates the conventioned /tmp secrets dir under a temp path."""
    path = tmp_path / "qall-secrets" / "dataloaders"
    monkeypatch.setenv("QALL_DATALOADERS_DIR", str(path))
    return path


@pytest.fixture
def fake_keyring(monkeypatch):
    """In-memory keyring backend, isolated per test."""
    store = {}

    def set_password(service, user, password):
        store[(service, user)] = password

    def get_password(service, user):
        return store.get((service, user))

    def delete_password(service, user):
        store.pop((service, user), None)

    monkeypatch.setattr(credential_module.keyring, "set_password", set_password)
    monkeypatch.setattr(credential_module.keyring, "get_password", get_password)
    monkeypatch.setattr(credential_module.keyring, "delete_password", delete_password)
    return store


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
) -> tuple[str, TaskNode]:
    payload = TaskPayload(
        code=source_code,
        code_format="raw",
        environment=TaskEnvironment(image="python:3.13").to_dict(),
        runtime={"qall_version": importlib.metadata.version("qall")},
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
        metadata=metadata,
    )
    node_block = node.to_block(DEFAULT_CODEC)
    store.put(node_block.hash, node_block.data)
    return node_block.hash, node


def test_provision_dag_files(
    config_path: Path, secrets_dir: Path, fake_keyring, file_src: Path, blockstore
):
    """The client provisions one resolved-secrets file per DAG node."""
    core_dl.add_dataloader(
        "mnist", f"file://{file_src}", "mnist", {"api_key": "s3cret"}
    )

    store, tmpdir = blockstore
    task_hash, node = _push_task(
        store, "def process(input):\n    return 0\n", "process", ["mnist"]
    )
    dag = TaskDag(nodes=[node], payloads=[], root_hash=task_hash)

    written = core_dl.provision_dataloader_files_for_dag(dag)
    assert len(written) == 1

    path = config_dl.dataloader_secrets_path(task_hash)
    assert path.exists()

    data = json.loads(path.read_text())
    assert data["mnist"]["src"] == f"file://{file_src}"
    assert data["mnist"]["dst"] == "mnist"
    # Secret is resolved to its plaintext in the provisioned file.
    assert data["mnist"]["creds"]["api_key"] == "s3cret"

    # Files 0400, directory 0700.
    assert (path.stat().st_mode & 0o777) == 0o400
    assert (path.parent.stat().st_mode & 0o777) == 0o700

    core_dl.cleanup_dataloader_files(written)
    assert not path.exists()


def test_executor_missing_secret_fails(
    config_path: Path, secrets_dir: Path, blockstore
):
    """A task referencing a dataloader with no provisioned file fails loudly."""
    store, tmpdir = blockstore
    task_hash, _ = _push_task(
        store, "def process(input):\n    return 0\n", "process", ["mnist"]
    )

    executor = TaskRuntimeExecutor(
        task_hash=task_hash,
        registry=BlockRegistry(tmpdir),
    )
    with pytest.raises(ValueError, match="no such dataloader"):
        executor.execute(
            task_run_id="missing-secret-run",
            input_artifact=cloudpickle.dumps({"args": (None,), "kwargs": {}}),
        )
