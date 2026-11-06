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

import typer
import uuid

from typing import Optional

from qall.core.daemon import (
    start_daemon,
    run_task,
    get_daemon_status,
    stop_daemon,
    restart_daemon,
)
from qall.cli.utils import parse_daemon_backend, parse_systemd_scope
from qall.daemon.systemd_manager import SystemdDaemonManager

daemon_cli = typer.Typer(
    name="daemon",
    help="Manage daemon",
    no_args_is_help=True,
)


def _manager_kwargs(
    scope: Optional[str] = None,
    unit_name: Optional[str] = None,
    unit_dir: Optional[str] = None,
) -> dict:
    """
    Collect optional daemon-manager keyword arguments, dropping unset ones.
    The CLI does not interpret these: only the selected backend manager uses
    them (systemd understands scope/unit_name/unit_dir; docker ignores them).
    """
    return {
        key: value
        for key, value in (
            ("scope", scope),
            ("unit_name", unit_name),
            ("unit_dir", unit_dir),
        )
        if value is not None
    }


@daemon_cli.command("start")
def daemon_start(
    port: int = typer.Option(50053, "--port", "-p", help="gRPC port for the daemon"),
    block_registry: str = typer.Option(
        None,
        "--block-dir",
        "-b",
        help="Path to block registry directory",
    ),
    artifact_registry: str = typer.Option(
        None,
        "--artifact-dir",
        "-a",
        help="Path to artifact registry directory",
    ),
    backend: str = typer.Option(
        "docker",
        "--daemon-backend",
        callback=parse_daemon_backend,
        help="Daemon backend to use: 'docker' or 'systemd'.",
    ),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        "-s",
        callback=parse_systemd_scope,
        help="systemd scope: 'user' or 'system' (default: user; systemd backend only).",
    ),
    unit_name: Optional[str] = typer.Option(
        None,
        "--unit-name",
        help="systemd unit name (default: qalld; systemd backend only).",
    ),
    unit_dir: Optional[str] = typer.Option(
        None,
        "--unit-dir",
        help="systemd unit directory (systemd backend only).",
    ),
):
    """
    Start a local Qall daemon (Docker or systemd backend).
    """
    try:
        start_daemon(
            port=port,
            block_registry_path=block_registry,
            artifact_registry_path=artifact_registry,
            backend=backend,
            **_manager_kwargs(scope, unit_name, unit_dir),
        )
    except KeyboardInterrupt:
        typer.echo("Daemon stopped.")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@daemon_cli.command("stop")
def daemon_stop(
    backend: str = typer.Option(
        "docker",
        "--daemon-backend",
        callback=parse_daemon_backend,
        help="Daemon backend to use: 'docker' or 'systemd'.",
    ),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        "-s",
        callback=parse_systemd_scope,
        help="systemd scope: 'user' or 'system' (default: user; systemd backend only).",
    ),
    unit_name: Optional[str] = typer.Option(
        None,
        "--unit-name",
        help="systemd unit name (default: qalld; systemd backend only).",
    ),
    unit_dir: Optional[str] = typer.Option(
        None,
        "--unit-dir",
        help="systemd unit directory (systemd backend only).",
    ),
):
    try:
        stop_daemon(backend=backend, **_manager_kwargs(scope, unit_name, unit_dir))
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@daemon_cli.command("restart")
def daemon_restart(
    port: int = typer.Option(50053, "--port", "-p", help="gRPC port for the daemon"),
    backend: str = typer.Option(
        "docker",
        "--daemon-backend",
        callback=parse_daemon_backend,
        help="Daemon backend to use: 'docker' or 'systemd'.",
    ),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        "-s",
        callback=parse_systemd_scope,
        help="systemd scope: 'user' or 'system' (default: user; systemd backend only).",
    ),
    unit_name: Optional[str] = typer.Option(
        None,
        "--unit-name",
        help="systemd unit name (default: qalld; systemd backend only).",
    ),
    unit_dir: Optional[str] = typer.Option(
        None,
        "--unit-dir",
        help="systemd unit directory (systemd backend only).",
    ),
):
    try:
        restart_daemon(
            port, backend=backend, **_manager_kwargs(scope, unit_name, unit_dir)
        )
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@daemon_cli.command("run")
def daemon_run(
    task_hash: str = typer.Argument(
        ..., help="Hash of the task stored in registry to execute."
    ),
    artifact_hash: str = typer.Option(
        None,
        "--artifact-hash",
        "-a",
        help="Hash of the input artifact stored in registry for the task execution.",
    ),
    daemon_address: Optional[str] = typer.Option(
        None,
        "--daemon-address",
        "-d",
        help="Daemon gRPC address (default: QALL_DAEMON_ADDRESS env var or localhost:50053)",
    ),
    block_registry: str = typer.Option(
        None,
        "--block-dir",
        "-b",
        help="Path to block registry directory",
    ),
    artifact_registry: str = typer.Option(
        None,
        "--artifact-dir",
        "-a",
        help="Path to artifact registry directory",
    ),
    timeout: int = typer.Option(
        300, "--timeout", "-t", help="Timeout for the task execution."
    ),
    workflow_run_id: Optional[str] = typer.Option(
        None,
        "--workflow-run-id",
        "-w",
        help="Workflow run identifier. The daemon scopes the task's shared "
        "filesystem (/workdir) per workflow run. When omitted, a fresh "
        "identifier is generated so the task still gets its own isolated run.",
    ),
    backend: str = typer.Option(
        "docker",
        "--daemon-backend",
        callback=parse_daemon_backend,
        help="Daemon backend to use: 'docker' or 'systemd'.",
    ),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        "-s",
        callback=parse_systemd_scope,
        help="systemd scope: 'user' or 'system' (default: user; systemd backend only).",
    ),
    unit_name: Optional[str] = typer.Option(
        None,
        "--unit-name",
        help="systemd unit name (default: qalld; systemd backend only).",
    ),
    unit_dir: Optional[str] = typer.Option(
        None,
        "--unit-dir",
        help="systemd unit directory (systemd backend only).",
    ),
):
    """
    Orders a local Daemon instance to start and execute a given task.
    """
    if not workflow_run_id:
        workflow_run_id = str(uuid.uuid4())
        typer.echo(
            f"No --workflow-run-id given; using a fresh run id: {workflow_run_id}"
        )

    try:
        artifacts = run_task(
            task_hash=task_hash,
            workflow_run_id=workflow_run_id,
            input_artifact_hash=artifact_hash,
            daemon_address=daemon_address,
            block_registry=block_registry,
            artifact_registry=artifact_registry,
            timeout=timeout,
            backend=backend,
            **_manager_kwargs(scope, unit_name, unit_dir),
        )

        if artifacts:
            typer.echo(f"Task completed successfully!")
            typer.echo(f"Output artifacts: {len(artifacts)}")

            for artifact in artifacts:
                typer.echo(f"  - {artifact.hash}")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@daemon_cli.command("status")
def daemon_status(
    daemon_address: Optional[str] = typer.Option(
        None,
        "--daemon-address",
        "-d",
        help="Daemon gRPC address (default: QALL_DAEMON_ADDRESS env var or localhost:50053)",
    ),
    block_registry: str = typer.Option(
        None,
        "--block-dir",
        "-b",
        help="Path to block registry directory",
    ),
    artifact_registry: str = typer.Option(
        None,
        "--artifact-dir",
        "-a",
        help="Path to artifact registry directory",
    ),
    backend: str = typer.Option(
        "docker",
        "--daemon-backend",
        callback=parse_daemon_backend,
        help="Daemon backend to use: 'docker' or 'systemd'.",
    ),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        "-s",
        callback=parse_systemd_scope,
        help="systemd scope: 'user' or 'system' (default: user; systemd backend only).",
    ),
    unit_name: Optional[str] = typer.Option(
        None,
        "--unit-name",
        help="systemd unit name (default: qalld; systemd backend only).",
    ),
    unit_dir: Optional[str] = typer.Option(
        None,
        "--unit-dir",
        help="systemd unit directory (systemd backend only).",
    ),
):
    """
    Check the status of the local daemon (Docker or systemd backend).
    """
    try:
        status = get_daemon_status(
            daemon_address=daemon_address,
            block_registry=block_registry,
            artifact_registry=artifact_registry,
            backend=backend,
            **_manager_kwargs(scope, unit_name, unit_dir),
        )

        if status:
            typer.echo(f"status: {status}")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@daemon_cli.command("install")
def daemon_install(
    scope: str = typer.Option(
        "user",
        "--scope",
        "-s",
        callback=parse_systemd_scope,
        help="systemd scope: 'user' or 'system' (default: user)",
    ),
    enable_now: bool = typer.Option(
        True,
        "--enable-now/--no-enable-now",
        help="Enable and start the daemon right after installing the unit.",
    ),
):
    """
    Install the Qall daemon as a native systemd unit (systemd backend).
    """
    try:
        manager = SystemdDaemonManager(scope=scope)
        manager.install(enable_now=enable_now)
        typer.echo(f"Installed systemd unit {manager.unit_file}.")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@daemon_cli.command("uninstall")
def daemon_uninstall(
    scope: str = typer.Option(
        "user",
        "--scope",
        "-s",
        callback=parse_systemd_scope,
        help="systemd scope: 'user' or 'system' (default: user)",
    ),
):
    """
    Remove the Qall daemon systemd unit for the given scope (systemd backend).
    """
    try:
        SystemdDaemonManager(scope=scope).uninstall()
        typer.echo("Uninstalled the Qall daemon systemd unit.")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
