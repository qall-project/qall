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

import hashlib
import sqlite3

from pathlib import Path

import cloudpickle
import pytest
from typer.testing import CliRunner

from qall.core import artifact
from qall.cli.artifact import artifact_cli


def _write_block(root: Path, hash: str, payload: bytes) -> Path:
    block_path = root / "blocks" / hash[:2] / hash[2:]
    block_path.parent.mkdir(parents=True, exist_ok=True)
    block_path.write_bytes(payload)
    return block_path


def _hash_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture
def artifact_store(tmp_path: Path) -> tuple[Path, dict]:
    """Build a fake artifact-registry dir (sharded blocks layout + optional sqlite meta)."""
    root = tmp_path / "artifact-registry"

    payload = cloudpickle.dumps({"answer": 42})
    hash = _hash_of(payload)
    _write_block(root, hash, payload)

    raw_payload = b"\x00\x01not-cloudpickle"
    raw_hash = _hash_of(raw_payload)
    _write_block(root, raw_hash, raw_payload)

    db_path = root / "daemon_state.db"
    con = sqlite3.connect(db_path)
    con.execute(
        """
        CREATE TABLE artifacts_meta (
            hash TEXT NOT NULL,
            task_run_id TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (hash, task_run_id)
        )
        """
    )
    con.execute(
        "INSERT INTO artifacts_meta VALUES (?, ?, ?)",
        (hash, "task-123", "2026-09-24 10:00:00"),
    )
    con.commit()
    con.close()

    return root, {"hash": hash, "raw_hash": raw_hash}


def test_list_local_artifacts(artifact_store):
    root, keys = artifact_store
    artifacts = artifact.list_local_artifacts(str(root))

    assert {a.hash for a in artifacts} == {keys["hash"], keys["raw_hash"]}


def test_get_local_artifact_metadata(artifact_store):
    root, keys = artifact_store
    art = artifact.get_local_artifact(keys["hash"], str(root))

    assert art.hash == keys["hash"]
    assert art.size == len(cloudpickle.dumps({"answer": 42}))
    assert art.task_run_id == "task-123"
    assert art.created_at is not None


def test_get_local_artifact_missing_raises(artifact_store):
    root, _ = artifact_store
    with pytest.raises(FileNotFoundError):
        artifact.get_local_artifact("deadbeef" * 8, str(root))


def test_deserialize_local_artifact(artifact_store):
    root, keys = artifact_store
    value = artifact.deserialize_local_artifact(keys["hash"], str(root))

    assert value == {"answer": 42}


def test_deserialize_local_artifact_fallback_to_raw(artifact_store):
    root, keys = artifact_store
    value = artifact.deserialize_local_artifact(keys["raw_hash"], str(root))

    assert value == b"\x00\x01not-cloudpickle"


def test_read_local_artifact_bytes(artifact_store):
    root, keys = artifact_store
    payload = artifact.read_local_artifact_bytes(keys["hash"], str(root))

    assert cloudpickle.loads(payload) == {"answer": 42}


runner = CliRunner()


def test_cli_artifact_ls_local(artifact_store):
    root, keys = artifact_store
    result = runner.invoke(artifact_cli, ["ls", "--local", "--artifact-dir", str(root)])

    assert result.exit_code == 0
    assert keys["hash"] in result.output


def test_cli_artifact_info_local(artifact_store):
    root, keys = artifact_store
    result = runner.invoke(
        artifact_cli,
        ["info", keys["hash"], "--local", "--artifact-dir", str(root)],
    )

    assert result.exit_code == 0
    assert keys["hash"] in result.output
    assert "task-123" in result.output


def test_cli_artifact_show_local(artifact_store):
    root, keys = artifact_store
    result = runner.invoke(
        artifact_cli,
        ["show", keys["hash"], "--local", "--artifact-dir", str(root)],
    )

    assert result.exit_code == 0
    assert "{'answer': 42}" in result.output


def test_cli_artifact_show_local_raw(artifact_store):
    root, keys = artifact_store
    result = runner.invoke(
        artifact_cli,
        ["show", keys["hash"], "--local", "--raw", "--artifact-dir", str(root)],
    )

    assert result.exit_code == 0
