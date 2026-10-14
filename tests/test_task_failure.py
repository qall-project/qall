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
from docker.errors import NotFound

from qall.core import daemon
from qall.core.daemon import _format_task_failure
from qall.daemon.docker_manager import DockerDaemonManager
from qall_daemon_client.v1.objects import TaskRun, TaskRunStatus


def test_format_task_failure_includes_stdout_and_stderr():
    report = _format_task_failure(
        task_hash="hash123",
        task_run_id="run-12345678",
        stdout="line from stdout",
        stderr="line from stderr",
    )

    assert "Task hash123 (run run-12345678) failed." in report
    assert "[stdout]" in report
    assert "line from stdout" in report
    assert "[stderr]" in report
    assert "line from stderr" in report


def test_format_task_failure_handles_empty_streams():
    report = _format_task_failure(
        task_hash="hash123",
        task_run_id="run-12345678",
        stdout="",
        stderr="",
    )

    assert "(empty)" in report


def _fake_container(stdout: bytes, stderr: bytes):
    container = MagicMock()

    def logs(stdout=True, stderr=False, **kwargs):
        if stdout:
            return stdout_bytes
        return stderr_bytes

    stdout_bytes = stdout
    stderr_bytes = stderr
    container.logs.side_effect = logs
    return container


def _build_manager(container=None, missing=False):
    docker_client = MagicMock()

    if missing:
        docker_client.containers.get.side_effect = NotFound("no such container")
    else:
        docker_client.containers.get.return_value = container

    with patch(
        "qall.daemon.docker_manager.docker.from_env",
        return_value=docker_client,
    ):
        return DockerDaemonManager(image="scw/qall-daemon-server:latest")


def test_task_logs_returns_stdout_and_stderr():
    manager = _build_manager(container=_fake_container(b"out line\n", b"err line\n"))

    stdout, stderr = manager.task_logs("run-12345678")

    assert stdout == "out line\n"
    assert stderr == "err line\n"


def test_task_logs_missing_container_returns_empty():
    manager = _build_manager(missing=True)

    stdout, stderr = manager.task_logs("run-12345678")

    assert stdout == ""
    assert stderr == ""


def test_run_task_logs_stdout_stderr_on_error(caplog):
    fake_mgr = MagicMock()
    fake_mgr.service_info.return_value = True
    fake_mgr.task_logs.return_value = ("task stdout line", "task stderr line")

    client = MagicMock()
    client.get_service_info.return_value = MagicMock()
    client.create_task_run.return_value = TaskRun(
        id="run-12345678", status=TaskRunStatus.RUNNING
    )
    client.wait_for_task_run.return_value = TaskRun(
        id="run-12345678", status=TaskRunStatus.ERROR
    )
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    fake_mgr.client = client

    with patch(
        "qall.core.daemon.DockerDaemonManager",
        return_value=fake_mgr,
    ):
        with pytest.raises(RuntimeError, match="Task failed with status: ERROR"):
            daemon.run_task(
                task_hash="hash123",
                daemon_address="127.0.0.1:50053",
            )

    assert "task stdout line" in caplog.text
    assert "task stderr line" in caplog.text
    fake_mgr.task_logs.assert_called_once_with("run-12345678")
