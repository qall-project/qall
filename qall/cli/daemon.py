# Copyright 2026 Scaleway
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import typer

from typing import Optional

from qorus.core.daemon import (
    start_daemon,
    run_task,
    get_daemon_status,
    stop_daemon,
    restart_daemon,
)

daemon_cli = typer.Typer(
    name="daemon",
    help="Manage daemon",
    no_args_is_help=True,
)


@daemon_cli.command("start")
def daemon_start(
    port: int = typer.Option(50053, "--port", "-p", help="gRPC port for the daemon"),
    image: str = typer.Option(
        None,
        "--image",
        "-i",
        help="Daemon Docker image to use",
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
    worker_provider: str = typer.Option(
        None,
        "--worker-provider",
        "-w",
        help="Name of the worker provider",
    ),
):
    """
    Start a local Qorus daemon in a Docker container.
    """
    try:
        start_daemon(
            port=port,
            block_registry_path=block_registry,
            artifact_registry_path=artifact_registry,
            image=image,
            worker_provider=worker_provider,
        )
    except KeyboardInterrupt:
        typer.echo("Daemon stopped.")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@daemon_cli.command("stop")
def daemon_stop(
    port: int = typer.Option(50053, "--port", "-p", help="gRPC port for the daemon"),
):
    try:
        stop_daemon(port)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@daemon_cli.command("restart")
def daemon_restart(
    port: int = typer.Option(50053, "--port", "-p", help="gRPC port for the daemon"),
):
    try:
        restart_daemon(port)
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
    daemon_image: str = typer.Option(
        None,
        "--daemon-image",
        "-i",
        help="Daemon Docker image to use",
    ),
    daemon_address: Optional[str] = typer.Option(
        None,
        "--daemon-address",
        "-d",
        help="Daemon gRPC address (default: QORUS_DAEMON_ADDRESS env var or localhost:50053)",
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
    worker_provider: str = typer.Option(
        None,
        "--worker-provider",
        "-w",
        help="Name of the worker provider",
    ),
    timeout: int = typer.Option(
        300, "--timeout", "-t", help="Timeout for the task execution."
    ),
):
    """
    Orders a local Daemon instance to start and execute a given task.
    """
    try:
        artifacts = run_task(
            task_hash=task_hash,
            input_artifact_hash=artifact_hash,
            daemon_address=daemon_address,
            block_registry=block_registry,
            artifact_registry=artifact_registry,
            daemon_image=daemon_image,
            timeout=timeout,
            worker_provider=worker_provider,
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
    daemon_image: str = typer.Option(
        None,
        "--daemon-image",
        "-i",
        help="Daemon Docker image to use",
    ),
    daemon_address: Optional[str] = typer.Option(
        None,
        "--daemon-address",
        "-d",
        help="Daemon gRPC address (default: QORUS_DAEMON_ADDRESS env var or localhost:50053)",
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
):
    """
    Check the status of the local daemon container.
    """
    try:
        status = get_daemon_status(
            daemon_image=daemon_image,
            daemon_address=daemon_address,
            block_registry=block_registry,
            artifact_registry=artifact_registry,
        )

        if status:
            typer.echo(f"status: {status}")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
