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

import qorus.core as core

workflow_cli = typer.Typer(
    name="workflow",
    help="Manage and control lifecycle workflows.",
    no_args_is_help=True,
)


@workflow_cli.command("create")
def workflow_create(
    uri: str = typer.Argument(
        ..., help="Target canonical URI string formatted as 'name:version'."
    ),
    profile: str = typer.Argument(
        ..., help="The resource profile name to apply to this orchestration model."
    ),
):
    """Register or update a formal workflow definition inside the cloud provider control plane infrastructure."""
    if ":" not in uri:
        typer.echo(
            "Error: URI must match the 'name:version' format constraint.", err=True
        )
        raise typer.Exit(code=1)
    name, version = uri.split(":", 1)

    wf = core.create_workflow(
        workflow_name=name, workflow_version=version, profile=profile
    )
    typer.echo(
        f"Workflow reference compiled on provider ecosystem. Endpoint: {wf.endpoint}"
    )


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
    run_obj = core.run_workflow(workflow_id=workflow_id)
    typer.echo(f"Workflow run triggered execution sequence. Run ID: {run_obj.id}")
