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

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from qall.cli.daemon import daemon_cli
from qall.core.daemon import (
    get_daemon_status,
    run_task,
    start_daemon,
    stop_daemon,
)
from qall.object import DaemonStatus, TaskRunStatus

runner = CliRunner()


# daemon-backend option


def test_daemon_start_defaults_to_docker_backend():
    with patch("qall.cli.daemon.start_daemon") as m_start:
        result = runner.invoke(daemon_cli, ["start", "--port", "53000"])

    assert result.exit_code == 0, result.output
    m_start.assert_called_once()
    assert m_start.call_args.kwargs["backend"] == "docker"


def test_daemon_start_selects_systemd_backend():
    with patch("qall.cli.daemon.start_daemon") as m_start:
        result = runner.invoke(daemon_cli, ["start", "--daemon-backend", "systemd"])

    assert result.exit_code == 0, result.output
    assert m_start.call_args.kwargs["backend"] == "systemd"


def test_daemon_backend_is_case_insensitive():
    with patch("qall.cli.daemon.start_daemon") as m_start:
        result = runner.invoke(daemon_cli, ["start", "--daemon-backend", "SYSTEMD"])

    assert result.exit_code == 0, result.output
    assert m_start.call_args.kwargs["backend"] == "systemd"


def test_daemon_backend_rejects_unknown_value():
    result = runner.invoke(daemon_cli, ["start", "--daemon-backend", "kubernetes"])

    assert result.exit_code != 0
    assert "kubernetes" in result.output


def test_daemon_stop_selects_systemd_backend():
    with patch("qall.cli.daemon.stop_daemon") as m_stop:
        result = runner.invoke(daemon_cli, ["stop", "--daemon-backend", "systemd"])

    assert result.exit_code == 0, result.output
    assert m_stop.call_args.kwargs["backend"] == "systemd"


def test_daemon_restart_selects_systemd_backend():
    with patch("qall.cli.daemon.restart_daemon") as m_restart:
        result = runner.invoke(daemon_cli, ["restart", "--daemon-backend", "systemd"])

    assert result.exit_code == 0, result.output
    assert m_restart.call_args.kwargs["backend"] == "systemd"


def test_daemon_status_selects_systemd_backend():
    with patch("qall.cli.daemon.get_daemon_status") as m_status:
        result = runner.invoke(daemon_cli, ["status", "--daemon-backend", "systemd"])

    assert result.exit_code == 0, result.output
    assert m_status.call_args.kwargs["backend"] == "systemd"


def test_daemon_run_selects_systemd_backend():
    with patch("qall.cli.daemon.run_task", return_value=[]) as m_run:
        result = runner.invoke(
            daemon_cli, ["run", "hash123", "--daemon-backend", "systemd"]
        )

    assert result.exit_code == 0, result.output
    assert m_run.call_args.kwargs["backend"] == "systemd"


# install / uninstall


def test_daemon_install_uses_systemd_manager_scope():
    fake_manager = MagicMock()
    with patch(
        "qall.cli.daemon.SystemdDaemonManager", return_value=fake_manager
    ) as m_cls:
        result = runner.invoke(daemon_cli, ["install", "--scope", "user"])

    assert result.exit_code == 0, result.output
    m_cls.assert_called_once_with(scope="user")
    fake_manager.install.assert_called_once_with(enable_now=True)


def test_daemon_install_no_enable_now():
    fake_manager = MagicMock()
    with patch("qall.cli.daemon.SystemdDaemonManager", return_value=fake_manager):
        result = runner.invoke(daemon_cli, ["install", "--no-enable-now"])

    assert result.exit_code == 0, result.output
    fake_manager.install.assert_called_once_with(enable_now=False)


def test_daemon_uninstall_uses_systemd_manager_scope():
    fake_manager = MagicMock()
    with patch(
        "qall.cli.daemon.SystemdDaemonManager", return_value=fake_manager
    ) as m_cls:
        result = runner.invoke(daemon_cli, ["uninstall", "--scope", "system"])

    assert result.exit_code == 0, result.output
    m_cls.assert_called_once_with(scope="system")
    fake_manager.uninstall.assert_called_once()


def test_daemon_install_rejects_unknown_scope():
    result = runner.invoke(daemon_cli, ["install", "--scope", "kubernetes"])

    assert result.exit_code != 0
    assert "kubernetes" in result.output


# backend propagation in core


def _fake_manager():
    fake = MagicMock()
    fake.service_info.return_value = False
    fake.logs.return_value = None
    return fake


def test_start_daemon_forwards_backend_to_selector(tmp_path):
    fake = _fake_manager()
    with patch("qall.core.daemon.get_daemon_manager", return_value=fake) as m_get:
        start_daemon(
            backend="systemd",
            block_registry_path=str(tmp_path / "blocks"),
            artifact_registry_path=str(tmp_path / "artifacts"),
        )

    m_get.assert_called_once()
    assert m_get.call_args.kwargs["backend"] == "systemd"
    assert m_get.call_args.kwargs["grpc_port"] == 50053
    fake.start.assert_called_once()


def test_stop_daemon_forwards_backend_to_selector():
    fake = MagicMock()
    fake.is_running.return_value = False
    with patch("qall.core.daemon.get_daemon_manager", return_value=fake) as m_get:
        stop_daemon(backend="systemd")

    assert m_get.call_args.kwargs["backend"] == "systemd"


def test_get_daemon_status_forwards_backend_to_selector():
    fake = MagicMock()
    fake.service_info.return_value = True
    with patch("qall.core.daemon.get_daemon_manager", return_value=fake) as m_get:
        status = get_daemon_status(
            backend="systemd",
            block_registry="/tmp/qall-blocks",
            artifact_registry="/tmp/qall-artifacts",
        )

    assert m_get.call_args.kwargs["backend"] == "systemd"
    assert status.status == DaemonStatus.RUNNING


def test_run_task_forwards_backend_and_ensures_running(tmp_path):
    fake = MagicMock()

    done_run = MagicMock()
    done_run.status = TaskRunStatus.DONE

    client = MagicMock()
    client.__enter__.return_value = client
    client.get_service_info.return_value = MagicMock()
    client.create_task_run.return_value = done_run
    client.wait_for_task_run.return_value = done_run
    client.list_artifacts.return_value = []
    fake.client = client

    with (
        patch("qall.core.daemon.get_daemon_manager", return_value=fake) as m_get,
        patch("qall.core.daemon.provision_dataloader_file_for_task", return_value=None),
    ):
        artifacts = run_task(
            task_hash="hash123",
            block_registry=str(tmp_path / "blocks"),
            artifact_registry=str(tmp_path / "artifacts"),
            backend="systemd",
        )

    assert m_get.call_args.kwargs["backend"] == "systemd"
    fake.ensure_running.assert_called_once()
    assert artifacts == []
