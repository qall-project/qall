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
Unit tests for the host-volume plumbing of the Docker daemon manager.

Dataloader v2 replaces the in-container fsspec shim with real kernel mounts: the
daemon creates an rclone-backed Docker volume per
``(workflow_run_id, dataloader_name)`` under a host directory that must be
bind-mounted 1:1 into the daemon container. These tests pin that wiring without
requiring a real Docker daemon (``docker.from_env`` is mocked, as in
``test_task_failure.py``).
"""

import builtins
import inspect
import pathlib
import stat

from pathlib import Path
from unittest.mock import MagicMock, patch

from docker.errors import NotFound

import qall.config.dataloader as config_dataloader
import qall.runtime.dataloader as runtime_dataloader
from qall.config.paths import DEFAULT_HOST_VOLUMES_ROOT
from qall.daemon.docker_manager import (
    DockerDaemonManager,
    dataloader_volumes_dir,
)
from qall.runtime.subprocessor import run_task_in_subprocess


def _build_manager(registry_root: Path):
    """Build a manager backed by a mocked Docker client."""
    docker_client = MagicMock()
    docker_client.containers.list.return_value = []
    docker_client.containers.get.side_effect = NotFound("no such container")
    docker_client.containers.run.return_value = MagicMock(short_id="abc123456")

    with patch(
        "qall.daemon.docker_manager.docker.from_env",
        return_value=docker_client,
    ):
        manager = DockerDaemonManager(
            host_block_registry_path=registry_root / "blocks",
            host_artifact_registry_path=registry_root / "artifacts",
        )
    return manager, docker_client


def test_create_host_volumes_creates_unifs_dataloaders_and_blocks(
    tmp_path, monkeypatch
):
    root = tmp_path / "host-volumes"
    monkeypatch.setenv("QALL_HOST_VOLUMES_ROOT", str(root))
    manager, _ = _build_manager(tmp_path)

    manager._create_host_volumes()

    resolved_root = root.resolve()
    for directory in (resolved_root / "unifs", resolved_root / "dataloaders"):
        assert directory.is_dir(), f"missing host volume dir {directory}"
        # 0777: the root daemon and the unprivileged client must both write here.
        assert stat.S_IMODE(directory.stat().st_mode) == 0o777
    # Block registry shard root is pre-created too (client-owned).
    assert (tmp_path / "blocks" / "blocks").is_dir()


def test_start_daemon_passes_host_volumes_root_and_binds_dataloaders(
    tmp_path, monkeypatch
):
    root = tmp_path / "host-volumes"
    monkeypatch.setenv("QALL_HOST_VOLUMES_ROOT", str(root))
    manager, docker_client = _build_manager(tmp_path)

    manager._start_daemon()

    run_kwargs = docker_client.containers.run.call_args.kwargs
    command = run_kwargs["command"]
    volumes = run_kwargs["volumes"]

    resolved_root = root.resolve()
    assert f"--host-volumes-root={resolved_root}" in command
    assert "--host-task-dir=" + str(tmp_path / "blocks") in command

    dataloaders_dir = str(resolved_root / "dataloaders")
    unifs_dir = str(resolved_root / "unifs")
    # 1:1 bind mounts: the same string is the host source and the container target.
    assert volumes[dataloaders_dir] == {"bind": dataloaders_dir, "mode": "rw"}
    assert volumes[unifs_dir] == {"bind": unifs_dir, "mode": "rw"}
    assert volumes["/var/run/docker.sock"] == {
        "bind": "/var/run/docker.sock",
        "mode": "rw",
    }
    assert volumes["/tmp/qall-secrets"] == {
        "bind": "/tmp/qall-secrets",
        "mode": "rw",
    }


def test_dataloader_volumes_dir_honours_env_and_resolves_symlinks(
    tmp_path, monkeypatch
):
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    symlink_root = tmp_path / "link-root"
    symlink_root.symlink_to(real_root, target_is_directory=True)

    monkeypatch.setenv("QALL_HOST_VOLUMES_ROOT", str(symlink_root))
    assert dataloader_volumes_dir() == real_root.resolve() / "dataloaders"

    # An explicit root goes through the same canonicalisation.
    assert dataloader_volumes_dir(symlink_root) == real_root.resolve() / "dataloaders"


def test_dataloader_volumes_dir_defaults_to_host_volumes_root(monkeypatch):
    monkeypatch.delenv("QALL_HOST_VOLUMES_ROOT", raising=False)
    assert (
        dataloader_volumes_dir() == DEFAULT_HOST_VOLUMES_ROOT.resolve() / "dataloaders"
    )


def test_teardown_host_volumes_does_not_raise_on_permission_error(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setenv("QALL_HOST_VOLUMES_ROOT", str(tmp_path / "host-volumes"))
    manager, _ = _build_manager(tmp_path)

    # The (root) daemon / rclone plugin own the sub-directories: an unprivileged
    # rmtree can fail, and cleanup must stay best-effort.
    with patch(
        "qall.daemon.docker_manager.shutil.rmtree",
        side_effect=PermissionError("denied"),
    ) as rmtree:
        manager._teardown_host_volumes()

    assert rmtree.call_count == 2  # unifs + dataloaders
    assert "Could not fully remove host volume directory" in caplog.text


def test_teardown_host_volumes_removes_both_dirs(tmp_path, monkeypatch):
    root = tmp_path / "host-volumes"
    monkeypatch.setenv("QALL_HOST_VOLUMES_ROOT", str(root))
    manager, _ = _build_manager(tmp_path)
    manager._create_host_volumes()

    manager._teardown_host_volumes()

    assert not (root.resolve() / "unifs").exists()
    assert not (root.resolve() / "dataloaders").exists()


def test_config_dataloader_no_longer_provisions_task_secrets():
    for removed in (
        "dataloaders_secrets_dir",
        "dataloader_secrets_path",
        "write_dataloader_secrets",
        "read_dataloader_secrets",
        "cleanup_dataloader_secrets",
        "_DEFAULT_DATALOADERS_SECRETS_DIR",
        "_SECRETS_DIR_MODE",
        "_SECRETS_FILE_MODE",
    ):
        assert not hasattr(config_dataloader, removed), f"{removed} should be gone"

    # The credential/keyring machinery is untouched.
    for kept in (
        "resolve_secrets",
        "store_secrets",
        "delete_secrets",
        "obfuscate_creds",
        "load_config",
        "save_config",
    ):
        assert hasattr(config_dataloader, kept), f"{kept} must be kept"


def test_runtime_dataloader_no_longer_installs_stdlib_shims():
    for removed in (
        "bind_dataloader",
        "bind_dataloaders",
        "unbind_dataloaders",
        "reset",
        "_install_shims",
        "QallPath",
        "_qall_open",
        "_MOUNTS",
        "_INSTALLED",
    ):
        assert not hasattr(runtime_dataloader, removed), f"{removed} should be gone"

    # No stdlib patching is in place.
    assert builtins.open is not getattr(runtime_dataloader, "_qall_open", None)
    assert pathlib.Path is not getattr(runtime_dataloader, "QallPath", None)

    # Only the client-side reachability helpers remain.
    assert callable(runtime_dataloader.build_fs)
    assert callable(runtime_dataloader.check_reachable)


def test_subprocess_runner_has_no_dataloader_bootstrap():
    parameters = inspect.signature(run_task_in_subprocess).parameters
    assert "dataloaders_file" not in parameters
