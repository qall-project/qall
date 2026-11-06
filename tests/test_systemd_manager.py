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

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from qall.daemon.systemd_manager import (
    DEFAULT_UNIT_NAME,
    SYSTEM_BLOCK_REGISTRY_PATH,
    SYSTEM_ARTIFACT_REGISTRY_PATH,
    SYSTEM_DAEMON_BINARY,
    USER_BLOCK_REGISTRY_PATH,
    USER_ARTIFACT_REGISTRY_PATH,
    USER_DAEMON_BINARY,
    USER_UNIT_DIR,
    SystemdDaemonManager,
    systemd_ctl_args,
    _SYSTEM_UNIT_TEMPLATE_RESOURCE,
    _USER_UNIT_TEMPLATE_RESOURCE,
)


def _proc(returncode=0, stdout="", stderr=""):
    """Shortcut to build a CompletedProcess stand-in."""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _manager(tmp_path: Path, scope: str = "system", **kwargs) -> SystemdDaemonManager:
    return SystemdDaemonManager(
        scope=scope,
        unit_dir=tmp_path,
        daemon_binary="/usr/local/bin/qall-daemon",
        host_block_registry_path="/var/cache/qall/block-registry",
        host_artifact_registry_path="/var/cache/qall/artifact-registry",
        **kwargs,
    )


def test_invalid_scope_raises_value_error():
    with pytest.raises(ValueError, match="Unsupported systemd scope"):
        SystemdDaemonManager(scope="invalid")


def test_systemd_ctl_args():
    assert systemd_ctl_args("system") == ["systemctl"]
    assert systemd_ctl_args("user") == ["systemctl", "--user"]
    with pytest.raises(ValueError):
        systemd_ctl_args("bogus")


def test_default_scope_is_user():
    mgr = SystemdDaemonManager()
    assert mgr.scope == "user"
    assert mgr.unit_name == DEFAULT_UNIT_NAME
    assert mgr.grpc_port == 50053
    assert mgr.daemon_binary == str(USER_DAEMON_BINARY)
    assert mgr.host_block_registry_path == str(USER_BLOCK_REGISTRY_PATH)
    assert mgr.host_artifact_registry_path == str(USER_ARTIFACT_REGISTRY_PATH)
    assert mgr.unit_file == USER_UNIT_DIR / f"{DEFAULT_UNIT_NAME}.service"


def test_user_scope_defaults(tmp_path):
    mgr = _manager(tmp_path, scope="user")
    assert mgr._ctl == ["systemctl", "--user"]
    assert mgr.unit_file == tmp_path / f"{DEFAULT_UNIT_NAME}.service"


def test_is_running_active(tmp_path):
    mgr = _manager(tmp_path)
    with mock.patch(
        "qall.daemon.systemd_manager.subprocess.run",
        return_value=_proc(returncode=0),
    ) as run:
        assert mgr.is_running() is True
        assert run.call_args.args[0] == [
            "systemctl",
            "is-active",
            "--quiet",
            DEFAULT_UNIT_NAME,
        ]


def test_is_running_inactive(tmp_path):
    mgr = _manager(tmp_path)
    with mock.patch(
        "qall.daemon.systemd_manager.subprocess.run",
        return_value=_proc(returncode=3, stderr="inactive"),
    ):
        assert mgr.is_running() is False


def test_start_daemon_already_active_returns(tmp_path):
    mgr = _manager(tmp_path)
    with mock.patch(
        "qall.daemon.systemd_manager.subprocess.run",
        return_value=_proc(returncode=0),  # is-active -> active
    ) as run:
        mgr._start_daemon()
    # No "start" call: only the is-active probe happened.
    assert [c.args[0] for c in run.call_args_list] == [
        ["systemctl", "is-active", "--quiet", DEFAULT_UNIT_NAME]
    ]


def test_start_daemon_raises_without_unit(tmp_path):
    mgr = _manager(tmp_path)  # unit file not created in tmp_path
    with mock.patch(
        "qall.daemon.systemd_manager.subprocess.run",
        return_value=_proc(returncode=3),  # is-active -> inactive
    ):
        with pytest.raises(RuntimeError, match="Install it first"):
            mgr._start_daemon()


def test_start_daemon_starts_when_unit_present(tmp_path):
    mgr = _manager(tmp_path)
    mgr.unit_file.write_text("[Service]\n")

    with mock.patch(
        "qall.daemon.systemd_manager.subprocess.run",
        side_effect=[
            _proc(returncode=3),  # is-active -> inactive
            _proc(returncode=0),  # systemctl start
        ],
    ) as run:
        mgr._start_daemon()

    calls = [c.args[0] for c in run.call_args_list]
    assert ["systemctl", "start", DEFAULT_UNIT_NAME] in calls


def test_start_daemon_start_failure_raises(tmp_path):
    mgr = _manager(tmp_path)
    mgr.unit_file.write_text("[Service]\n")

    with mock.patch(
        "qall.daemon.systemd_manager.subprocess.run",
        side_effect=[
            _proc(returncode=3),
            _proc(returncode=1, stderr="job failed"),
        ],
    ):
        with pytest.raises(RuntimeError, match="Failed to start systemd unit"):
            mgr._start_daemon()


def test_stop_calls_systemctl_stop(tmp_path):
    mgr = _manager(tmp_path)
    with mock.patch(
        "qall.daemon.systemd_manager.subprocess.run",
        return_value=_proc(returncode=0),
    ) as run:
        mgr.stop()
    assert ["systemctl", "stop", DEFAULT_UNIT_NAME] in [
        c.args[0] for c in run.call_args_list
    ]


def test_install_writes_system_unit_and_enables(tmp_path):
    mgr = _manager(tmp_path)
    with mock.patch(
        "qall.daemon.systemd_manager.subprocess.run",
        return_value=_proc(returncode=0),
    ) as run:
        mgr.install()

    content = mgr.unit_file.read_text()
    assert "User=qall-daemon" in content
    assert "SupplementaryGroups=docker" in content
    assert "ExecStart=/usr/local/bin/qall-daemon" in content
    assert "--host-task-dir=/var/cache/qall/block-registry" in content
    assert "--block-registry-dir=/var/cache/qall/block-registry" in content
    assert "--artifact-registry-dir=/var/cache/qall/artifact-registry" in content
    assert "WantedBy=multi-user.target" in content

    cmds = [c.args[0] for c in run.call_args_list]
    assert ["systemctl", "daemon-reload"] in cmds
    assert ["systemctl", "enable", "--now", DEFAULT_UNIT_NAME] in cmds


def test_unit_templates_shipped_and_rendered():
    """
    The systemd templates live in the package data (not in the Python module)
    and render without leaving any placeholder unfilled.
    """
    from importlib.resources import files as resource_files

    for resource_name in (_SYSTEM_UNIT_TEMPLATE_RESOURCE, _USER_UNIT_TEMPLATE_RESOURCE):
        resource = resource_files("qall") / "data" / "systemd" / resource_name
        assert resource.is_file(), f"missing systemd template {resource_name}"
        assert "{binary}" in resource.read_text(encoding="utf-8")

    rendered = SystemdDaemonManager(scope="system")._unit_file_content()
    assert "{binary}" not in rendered
    assert "ExecStart=" in rendered
    for flag in (
        "--host-task-dir=",
        "--block-registry-dir=",
        "--artifact-registry-dir=",
    ):
        assert flag in rendered
    assert "/var/cache/qall/block-registry" in rendered

    user_rendered = SystemdDaemonManager(scope="user")._unit_file_content()
    assert "{binary}" not in user_rendered
    assert "WantedBy=default.target" in user_rendered


def test_install_user_scope_writes_user_unit_and_enables_linger(tmp_path):
    mgr = _manager(tmp_path, scope="user")
    with mock.patch(
        "qall.daemon.systemd_manager.subprocess.run",
        return_value=_proc(returncode=0),
    ) as run:
        mgr.install()

    content = mgr.unit_file.read_text()
    assert "WantedBy=default.target" in content
    assert "SupplementaryGroups" not in content

    cmds = [c.args[0] for c in run.call_args_list]
    assert ["systemctl", "--user", "enable", "--now", DEFAULT_UNIT_NAME] in cmds
    assert any(c[0] == "loginctl" and c[1] == "enable-linger" for c in cmds)


def test_install_not_now_only_enables(tmp_path):
    mgr = _manager(tmp_path)
    with mock.patch(
        "qall.daemon.systemd_manager.subprocess.run",
        return_value=_proc(returncode=0),
    ) as run:
        mgr.install(enable_now=False)

    cmds = [c.args[0] for c in run.call_args_list]
    assert ["systemctl", "enable", DEFAULT_UNIT_NAME] in cmds
    assert ["systemctl", "enable", "--now", DEFAULT_UNIT_NAME] not in cmds


def test_uninstall_removes_unit(tmp_path):
    mgr = _manager(tmp_path)
    mgr.unit_file.write_text("[Service]\n")

    with mock.patch(
        "qall.daemon.systemd_manager.subprocess.run",
        return_value=_proc(returncode=0),
    ) as run:
        mgr.uninstall()

    cmds = [c.args[0] for c in run.call_args_list]
    assert ["systemctl", "stop", DEFAULT_UNIT_NAME] in cmds
    assert ["systemctl", "disable", DEFAULT_UNIT_NAME] in cmds
    assert ["systemctl", "daemon-reload"] in cmds
    assert not mgr.unit_file.exists()


def test_logs_returns_none_when_not_running(tmp_path):
    mgr = _manager(tmp_path)
    with mock.patch(
        "qall.daemon.systemd_manager.subprocess.run",
        return_value=_proc(returncode=3),
    ):
        assert mgr.logs() is None


def test_logs_streams_journal_lines_when_running(tmp_path):
    mgr = _manager(tmp_path)
    fake_stdout = iter(["line 1\n", "line 2\n"])

    with (
        mock.patch(
            # Daemon considered active.
            "qall.daemon.systemd_manager.systemctl_is_active",
            return_value=True,
        ),
        mock.patch(
            "qall.daemon.systemd_manager.subprocess.Popen",
            return_value=mock.Mock(stdout=fake_stdout),
        ) as popen,
    ):
        lines = list(mgr.logs())

    assert lines == ["line 1\n", "line 2\n"]
    cmd = popen.call_args.args[0]
    assert cmd[0] == "journalctl"
    assert "-f" in cmd
    assert "-u" in cmd and DEFAULT_UNIT_NAME in cmd


def test_logs_user_scope_uses_journalctl_user(tmp_path):
    mgr = _manager(tmp_path, scope="user")
    with (
        mock.patch(
            "qall.daemon.systemd_manager.systemctl_is_active",
            return_value=True,
        ),
        mock.patch(
            "qall.daemon.systemd_manager.subprocess.Popen",
            return_value=mock.Mock(stdout=iter([])),
        ) as popen,
    ):
        list(mgr.logs())

    cmd = popen.call_args.args[0]
    assert "--user" in cmd
