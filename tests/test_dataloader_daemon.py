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
Dataloader tests for the daemon/container credential-passing path.

Cover:
  1. Client-side provisioning of `/dev/shm/qall-dataloaders/<hash>.json`
     from a pushed workflow DAG (dir 0700, files 0400, resolved creds).
  2. The executor preferring a pre-provisioned mount file over the host config
     (this is what the task container sees — the host config is NOT mounted).
  3. A full `-m daemon_integration` run through a running daemon (skipped when
     no daemon is reachable, or when the daemon image predates the dataloaders
     bind mount).
"""

import cloudpickle
import json
import shutil
import tempfile

from pathlib import Path

import pytest

from qall.core import dataloader as core_dl
from qall.config import dataloader as config_dl
from qall.registry import BlockRegistry
from qall.registry.blockstore import LocalBlockstore
from qall.runtime import TaskRuntimeExecutor, LocalArtifactBackend
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
    path = tmp_path / "qall-config.json"
    monkeypatch.setenv("QALL_CONFIG_PATH", str(path))
    return path


@pytest.fixture
def secrets_dir(tmp_path: Path, monkeypatch):
    """Isolates the conventioned /dev/shm secrets dir under a temp path."""
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


def test_executor_reads_provisioned_mount_file(
    config_path: Path,
    secrets_dir: Path,
    file_src: Path,
    blockstore,
):
    """
    The container path: a pre-provisioned secrets file (written by the host
    client) is used even though the host config inside the container is absent.
    """
    store, tmpdir = blockstore
    source_code = """
def process(input):
    from pathlib import Path
    with open("dataloaders/mnist/sub/a.txt") as f:
        first = f.read().strip()
    return {"first": first, "dirs": sorted(x.name for x in Path("dataloaders/mnist/sub").iterdir())}
"""
    task_hash, _ = _push_task(store, source_code, "process", ["mnist"])

    # Provision the mount file exactly like the client would. The host config
    # (`config_path`) does NOT contain "mnist", proving the file is the source
    # of truth inside the container.
    config_dl.write_dataloader_secrets(
        task_hash,
        {"mnist": {"src": f"file://{file_src}", "dst": "mnist", "creds": {}}},
    )

    executor = TaskRuntimeExecutor(
        task_hash=task_hash,
        registry=BlockRegistry(tmpdir),
        artifact_backend=LocalArtifactBackend(
            Path(tempfile.mkdtemp(prefix="dl-mount-art-")) / "a"
        ),
    )
    result = executor.execute(
        task_run_id="mount-file-run",
        input_artifact=cloudpickle.dumps({"args": (None,), "kwargs": {}}),
    )

    assert result.return_code == 0, result.stderr
    output = cloudpickle.loads(result.output_artifact_bytes)
    assert output["first"] == "hello dataloader"
    assert output["dirs"] == ["a.txt", "b.csv"]

    # The executor read the file but did not own it: it must NOT be removed.
    assert config_dl.dataloader_secrets_path(task_hash).exists()


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


@pytest.mark.daemon_integration
class TestDataloaderDaemonIntegration:
    """
    Full daemon/container dataloader path (`qall run --local` equivalent at the
    gRPC level). Requires a running daemon whose image includes the dataloaders
    bind mount (see SPEC Phase 1). Skipped when no daemon is reachable.
    """

    def test_dataloader_via_daemon(self, config_path: Path, file_src: Path, blockstore):
        from qall_daemon_client import GrpcDaemonClient, TaskRunStatus
        from qall.daemon.docker_manager import DockerDaemonManager

        store, tmpdir = blockstore
        source_code = """
def process(input):
    with open("dataloaders/mnist/sub/a.txt") as f:
        return f.read().strip()
"""
        task_hash, _ = _push_task(store, source_code, "process", ["mnist"])
        core_dl.add_dataloader("mnist", f"file://{file_src}", "mnist")

        # NOTE: no QALL_DATALOADERS_DIR override here — the secrets file must
        # land on the real conventioned mount (/dev/shm/qall-dataloaders)
        # which is what the daemon bind-mounts into every task container.
        written = core_dl.provision_dataloader_file_for_task(
            task_hash, BlockRegistry(tmpdir)
        )
        assert written is not None

        daemon_address = "localhost:50053"
        manager = DockerDaemonManager(
            image="scw/qall-daemon-server:latest",
            grpc_port=daemon_address.split(":")[-1],
            host_block_registry_path=str(tmpdir),
            host_artifact_registry_path=str(tmpdir / "artifacts"),
        )
        try:
            with manager as daemon:
                with GrpcDaemonClient(url=daemon_address) as client:
                    client.get_service_info()
        except Exception as e:
            pytest.skip(f"Daemon not available: {e}")

        try:
            with manager as daemon:
                with GrpcDaemonClient(url=daemon_address) as client:
                    input_data = cloudpickle.dumps({"args": (None,), "kwargs": {}})
                    artifact = client.create_artifact(
                        task_run_id="dataloader-daemon-input",
                        payload=input_data,
                    )
                    task_run = client.create_task_run(
                        task_hash=task_hash,
                        artifact_hash=artifact.hash,
                    )
                    completed = client.wait_for_task_run(
                        task_run_id=task_run.id,
                        timeout=120.0,
                    )
                    assert completed.status == TaskRunStatus.DONE, completed

                    artifacts = client.list_artifacts(task_run_id=task_run.id)
                    output = cloudpickle.loads(
                        client.download_artifact(artifacts[-1].hash)
                    )
                    assert output == "hello dataloader"
        finally:
            core_dl.cleanup_dataloader_files([written])
