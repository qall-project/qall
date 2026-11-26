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

import qall.core as core

from qall.registry import BlockRegistry
from qall.object import ExecutionMode

from typing import Optional

from .utils import pretty_artifact, pretty_workflow_build, pretty_workflow_plan

workflow_cli = typer.Typer(
    name="workflow",
    help="Manage and control lifecycle workflows.",
    no_args_is_help=True,
)


@workflow_cli.command("build")
def workflow_build(
    entrypoint: str = typer.Argument(
        ..., help="Path to the Python script containing tasks."
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Name of the workflow to declare. Script file name if not provided.",
    ),
    version: Optional[str] = typer.Option(
        "latest", "--version", "-v", help="Version tag for the target build."
    ),
):
    """Compile a workflow script into an IPLD DAG and push it to the registry."""
    try:
        tag, dag = core.build_workflow(
            entrypoint=entrypoint,
            workflow_name=name,
            workflow_version=version,
            local_only=True,
        )
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(pretty_workflow_build(tag, dag))


@workflow_cli.command("plan")
def workflow_plan(
    workflow_tag: str = typer.Argument(
        ..., help="Target workflow tag formatted as 'name:version' (or 'name')."
    ),
    profile: Optional[str] = typer.Option(
        None, "--profile", "-p", help="Target configuration profile name."
    ),
    allowed_qpus: Optional[list[str]] = typer.Option(
        None,
        "--allowed-qpu",
        "-q",
        help="Override allowed QPU from provided profile.",
    ),
    allowed_cpus: Optional[list[str]] = typer.Option(
        None,
        "--allowed-cpu",
        "-c",
        help="Override allowed CPU from provided profile.",
    ),
    allowed_gpus: Optional[list[str]] = typer.Option(
        None,
        "--allowed-gpu",
        "-g",
        help="Override allowed GPU from provided profile.",
    ),
    local: bool = typer.Option(
        True, "--local", "-l", help="Resolve classical tasks against local resources."
    ),
    clocal: bool = typer.Option(
        True,
        "--clocal",
        "-l",
        help="Resolve classical tasks against localhost and remote quantum resources by logged provider.",
    ),
):
    """Resolve hardware and quantum worker assignments for a built workflow."""
    try:
        if local and clocal:
            raise typer.BadParameter("Cannot combine CLI option --local and --clocal")

        execution_mode = ExecutionMode.remote

        if local:
            execution_mode = ExecutionMode.local
        elif clocal:
            execution_mode = ExecutionMode.classical_local_quantum_remote

        plan = core.plan_workflow(
            workflow_tag=workflow_tag,
            profile_name=profile,
            allowed_cpus=allowed_cpus,
            allowed_gpus=allowed_gpus,
            allowed_qpus=allowed_qpus,
            execution_mode=execution_mode,
        )
        dag = BlockRegistry(read_only=True).get_workflow_dag(plan.tag)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(pretty_workflow_plan(plan, dag))


@workflow_cli.command("info")
def workflow_info(
    workflow_id: str = typer.Argument(
        ..., help="The unique tracking identifier of the target workflow."
    )
):
    """Retrieve deep structure info and infrastructure metrics for a registered workflow asset."""
    # Assuming core tracking retrieval logic or printing simple data structures
    typer.echo(
        f"Fetching structural information boundaries for workflow ID: {workflow_id}"
    )
    raise NotImplementedError()


@workflow_cli.command("ls")
def workflow_list():
    """List all available workflows deployed across the active provider endpoint layout."""
    typer.echo("Listing available architecture workflows...")
    raise NotImplementedError()


@workflow_cli.command("run")
def workflow_run(
    workflow_id: str = typer.Argument(
        ..., help="The structural tracking ID of the pre-compiled workflow."
    )
):
    """Execute a pre-compiled workflow asset that has already been registered on the cloud platform."""
    run_obj, artifacts = core.run_workflow(workflow_id=workflow_id)
    typer.echo(f"Workflow run triggered execution sequence. Run ID: {run_obj.id}")

    # QoL: let the user launch `qall artifact show <hash>` to display the
    # actual output(s), annotated with the entrypoint task that produced them.

    if artifacts:
        typer.echo(pretty_artifact(artifacts))
