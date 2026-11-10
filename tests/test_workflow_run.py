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
Unit tests for the end-of-run QoL artifact hints in ``qall.core.workflow_run``:
the ``-> `qall artifact show <hash>``` lines emitted after a successful local
workflow run, annotated with the entrypoint task that produced the artifacts.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from qall.core.workflow_run import _artifact_show_hints, create_workflow_run
from qall.exceptions import DataloaderDependencyError
from qall.object import DaemonStatus, TaskDag, TaskMetadata, TaskNode, WorkflowRunStatus


def _node(name: str) -> TaskNode:
    """A TaskNode shaped like the ones BlockRegistry builds (dict metadata)."""
    return TaskNode(
        payload_hash=f"payload-{name}",
        resources={},
        children={},
        metadata={"name": name},
    )


def test_artifact_show_hints_emit_runable_commands():
    artifacts = [SimpleNamespace(hash="aaa111"), SimpleNamespace(hash="bbb222")]

    hints = _artifact_show_hints(artifacts)

    assert hints.splitlines() == [
        "To show an artifact, run the following command(s):",
        "\t-> 'qall artifact show aaa111'",
        "\t-> 'qall artifact show bbb222'",
    ]


def test_artifact_show_hints_without_task_name():
    hints = _artifact_show_hints([SimpleNamespace(hash="abc")])

    assert hints == (
        "To show an artifact, run the following command(s):\n"
        "\t-> 'qall artifact show abc'"
    )


def test_artifact_show_hints_skips_hashless_and_empty_inputs():
    artifacts = [SimpleNamespace(name="no-hash"), SimpleNamespace(hash="ok")]

    assert _artifact_show_hints(artifacts) == (
        "To show an artifact, run the following command(s):\n"
        "\t-> 'qall artifact show ok'"
    )

    assert _artifact_show_hints([]) == ""
    assert _artifact_show_hints(None) == ""


def test_local_run_preflights_dataloaders_before_starting_the_daemon(tmp_path):
    """A missing fuse/rclone must fail before any daemon is started.

    Regression: the local auto-start path started the daemon (and then followed
    its logs forever) before the dataloader pre-flight, so the dependency error
    was never surfaced when the daemon was down.
    """
    dag = SimpleNamespace(nodes=[], root_hash="root-hash")
    profile = SimpleNamespace(provider="local")
    local_config = MagicMock()
    local_config.get_default_profile.return_value = profile

    with (
        patch("qall.core.workflow_run.WorkflowSpec"),
        patch(
            "qall.core.workflow_run.push_workflow_on_registry",
            return_value=("workflow:latest", dag),
        ),
        patch(
            "qall.core.workflow_run.get_provider_login_credentials",
            return_value=None,
        ),
        patch("qall.core.workflow_run.config_exists", return_value=True),
        patch(
            "qall.core.workflow_run.get_local_configuration",
            return_value=local_config,
        ),
        patch(
            "qall.core.workflow_run.apply_resource_overrides",
            side_effect=lambda profile, **_: profile,
        ),
        patch("qall.core.workflow_run.resolve_workflow_resources", return_value={}),
        patch("qall.core.workflow_run._get_provider_workers", return_value=[]),
        patch(
            "qall.core.workflow_run.get_daemon_status",
            return_value=SimpleNamespace(status=DaemonStatus.STOPPED),
        ),
        patch(
            "qall.core.workflow_run.resolve_dataloaders_by_task",
            return_value=[{"name": "bucket", "src": "s3://bucket", "task_hash": "h"}],
        ),
        patch(
            "qall.core.workflow_run.ensure_remote_dataloader_support",
            side_effect=DataloaderDependencyError("fuse is missing"),
        ) as m_preflight,
        patch("qall.core.workflow_run.start_daemon") as m_start,
        patch("qall.core.workflow_run.run_task") as m_run,
        patch("qall.core.workflow_run.stop_daemon") as m_stop,
    ):
        result = create_workflow_run(
            entrypoint=str(tmp_path / "workflow.py"),
            local_only=True,
            auto_start_daemon=True,
        )

    assert result.status == WorkflowRunStatus.ERROR
    m_preflight.assert_called_once()
    m_start.assert_not_called()
    m_run.assert_not_called()
    m_stop.assert_not_called()
