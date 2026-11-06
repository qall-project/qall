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

import pytest

from qall.daemon import DockerDaemonManager, SystemdDaemonManager, get_daemon_manager
from qall.daemon.base_manager import BaseDaemonManager


def _docker_manager(**kwargs):
    """Build a DockerDaemonManager with a faked docker engine."""
    with patch(
        "qall.daemon.docker_manager.docker.from_env",
        return_value=MagicMock(),
    ):
        return get_daemon_manager(**kwargs)


# get_daemon_manager


def test_get_daemon_manager_defaults_to_docker():
    assert isinstance(_docker_manager(), DockerDaemonManager)


def test_get_daemon_manager_explicit_docker():
    assert isinstance(_docker_manager(backend="docker"), DockerDaemonManager)


def test_get_daemon_manager_explicit_systemd():
    assert isinstance(get_daemon_manager(backend="systemd"), SystemdDaemonManager)


def test_get_daemon_manager_backend_is_case_insensitive():
    assert isinstance(get_daemon_manager(backend="SYSTEMD"), SystemdDaemonManager)
    assert isinstance(_docker_manager(backend="Docker"), DockerDaemonManager)


def test_get_daemon_manager_forwards_kwargs():
    with patch(
        "qall.daemon.docker_manager.docker.from_env",
        return_value=MagicMock(),
    ):
        mgr = get_daemon_manager(grpc_port=50123)

    assert isinstance(mgr, DockerDaemonManager)
    assert mgr.grpc_port == 50123


def test_get_daemon_manager_unknown_backend_raises():
    with pytest.raises(ValueError, match="Unknown daemon backend"):
        get_daemon_manager(backend="kubernetes")


def test_get_daemon_manager_systemd_receives_scope():
    mgr = get_daemon_manager(backend="systemd", scope="user")
    assert isinstance(mgr, SystemdDaemonManager)
    assert mgr.scope == "user"


def test_get_daemon_manager_systemd_receives_unit_name_and_dir(tmp_path):
    mgr = get_daemon_manager(
        backend="systemd",
        scope="user",
        unit_name="customd",
        unit_dir=str(tmp_path),
    )
    assert isinstance(mgr, SystemdDaemonManager)
    assert mgr.unit_name == "customd"
    assert mgr.unit_file == tmp_path / "customd.service"


def test_get_daemon_manager_docker_ignores_systemd_only_kwargs():
    with patch(
        "qall.daemon.docker_manager.docker.from_env",
        return_value=MagicMock(),
    ):
        mgr = get_daemon_manager(
            backend="docker",
            scope="system",
            unit_name="qalld",
            unit_dir="/tmp",
        )

    assert isinstance(mgr, DockerDaemonManager)


# ensure_running


class _StubManager(BaseDaemonManager):
    """Minimal BaseDaemonManager so ensure_running() can be unit tested."""

    def __init__(self):
        self.grpc_port = 50053
        self._client = None
        self._start_called = 0

    def _start_daemon(self):
        self._start_called += 1

    def stop(self):
        pass

    def logs(self):
        return None

    def is_running(self):
        return self._start_called > 0


def test_ensure_running_starts_when_daemon_not_available():
    mgr = _StubManager()

    # Must stub service_info (not just _wait_for_health): a real daemon may be
    # listening on 50053 — e.g. left running by the session-scoped daemon_stack
    # fixture — and this test intentionally simulates "daemon not available".
    with (
        patch.object(BaseDaemonManager, "_wait_for_health", return_value=True),
        patch.object(mgr, "service_info", return_value=False),
    ):
        result = mgr.ensure_running()

    assert result is mgr
    assert mgr._start_called == 1


def test_ensure_running_is_noop_when_daemon_available():
    mgr = _StubManager()

    with patch.object(mgr, "service_info", return_value=True):
        mgr.ensure_running()

    assert mgr._start_called == 0
