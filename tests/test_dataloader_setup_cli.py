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

"""CLI tests for ``qall dataloader setup`` (checks never install implicitly)."""

from unittest.mock import patch

from typer.testing import CliRunner

from qall.cli.dataloader import dataloader_cli
from qall.daemon.dependencies import DependencyCheck, DependencyReport
from qall.exceptions import DataloaderDependencyError

runner = CliRunner()


def _report(ok: bool) -> DependencyReport:
    checks = [
        DependencyCheck(
            name="docker",
            ok=True,
            required=True,
            detail="Docker engine is reachable.",
        ),
        DependencyCheck(
            name="rclone-plugin",
            ok=ok,
            required=True,
            detail=(
                "rclone Docker volume plugin is installed."
                if ok
                else "rclone Docker volume plugin is not installed."
            ),
            hint=None if ok else "The plugin is required to mount remote storage.",
            fix=(
                None
                if ok
                else "docker plugin install rclone/docker-volume-rclone:amd64 "
                "--alias rclone --grant-all-permissions"
            ),
            fixable=True,
        ),
    ]
    return DependencyReport(platform="Linux", checks=checks)


def test_setup_check_passes_through_to_core():
    with patch(
        "qall.cli.dataloader.core.setup_dataloader_host_dependencies"
    ) as m_setup:
        m_setup.return_value = _report(ok=True)
        result = runner.invoke(dataloader_cli, ["setup", "--check"])

    assert result.exit_code == 0, result.output
    assert m_setup.call_args.kwargs["check_only"] is True
    assert "All dataloader host dependencies are satisfied." in result.output


def test_setup_reports_missing_dependencies_and_exits_non_zero():
    with patch(
        "qall.cli.dataloader.core.setup_dataloader_host_dependencies"
    ) as m_setup:
        m_setup.return_value = _report(ok=False)
        result = runner.invoke(dataloader_cli, ["setup", "--check"])

    assert result.exit_code == 1
    assert "1 required dependency(ies) missing." in result.output
    assert "grant-all-permissions" in result.output


def test_setup_without_yes_in_a_non_interactive_shell_does_not_install():
    """No TTY -> no prompt, no implicit privilege escalation (the error carries the fix)."""
    with patch(
        "qall.cli.dataloader.core.setup_dataloader_host_dependencies"
    ) as m_setup:
        m_setup.side_effect = DataloaderDependencyError(
            "1 required dependency(ies) missing.",
            hint="run `docker plugin install ...`",
        )
        result = runner.invoke(dataloader_cli, ["setup"])

    assert result.exit_code == 1
    assert m_setup.call_args.kwargs["assume_yes"] is False
    assert "Error:" in result.output


def test_setup_yes_propagates_assume_yes():
    with patch(
        "qall.cli.dataloader.core.setup_dataloader_host_dependencies"
    ) as m_setup:
        m_setup.return_value = _report(ok=True)
        result = runner.invoke(dataloader_cli, ["setup", "--yes"])

    assert result.exit_code == 0, result.output
    assert m_setup.call_args.kwargs["assume_yes"] is True
