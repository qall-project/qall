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
import os
import typer
import os

from typing import Optional

from qorus.core.runtime import execute_task, ExecutionMode

task_cli = typer.Typer(
    name="task",
    help="Manage task execution engine",
    no_args_is_help=True,
)


@task_cli.command("run")
def run(
    task_hash: str,
    task_run_id: str,
    artifact_hash: str = typer.Option(
        None,
        "--artifact-hash",
        "-a",
        help="Hash of the artifact to use as input for the task",
    ),
    block_registry: str = typer.Option(
        None,
        "--block-registry",
        "-l",
        help="Local registry directory",
    ),
    daemon_address: str = typer.Option(
        None,
        "--daemon-address",
        "-d",
        help="Daemon gRPC address (default: localhost:50053)",
    ),
    mode: Optional[str] = typer.Option(
        "daemon",
        "--mode",
        "-m",
        help="Execution mode: 'local' for daemonless, 'daemon' for daemon-based",
    ),
    worker_address: Optional[list[str]] = typer.Option(
        None,
        "--worker-address",
        "-w",
        help="Worker gRPC address",
    ),
):
    """
    Execute a task. Made for intra-container execution.
    """

    try:
        execution_mode = ExecutionMode(mode.lower())
    except ValueError:
        typer.echo(
            f"Error: Invalid execution mode '{mode}'. Must be 'local' or 'daemon'.",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(f"[Runtime] Executing in {execution_mode} mode")

    if not daemon_address:
        daemon_address = os.environ.get("QORUS_DAEMON_ADDRESS", "127.0.0.1:50053")

    task_output = execute_task(
        task_hash=task_hash,
        task_run_id=task_run_id,
        daemon_address=daemon_address,
        block_registry=block_registry,
        artifact_hash=artifact_hash,
        mode=execution_mode,
        worker_addresses=worker_address,
    )

    typer.echo(f"[Runtime] Task done!")

    if task_output.return_code == 0:
        log = f" Task {task_hash} successful! " + (
            "Output artifact hash: " + task_output.output_artifact_hash
            if task_output.output_artifact_hash
            else "No output (no artifact created)."
        )
    else:
        log = f" Task {task_hash} failed with code {task_output.return_code}."

    typer.echo("[Runtime]" + log)

    typer.echo("[Runtime]Task logs:")
    typer.echo("[Runtime]" + "-" * 20)
    typer.echo("[Runtime] stdout:")
    typer.echo(task_output.stdout.replace("\n", "\n[Runtime]\t"))
    typer.echo("[Runtime]" + "-" * 20)
    typer.echo("[Runtime] stderr:")
    typer.echo("[Runtime] " + task_output.stderr.replace("\n", "\n[Runtime]\t"))

    raise typer.Exit(code=task_output.return_code)
