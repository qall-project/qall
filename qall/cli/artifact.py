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

from qorus.core import artifact

artifact_cli = typer.Typer(
    name="artifact",
    help="Inspect and download generated execution artifacts.",
    no_args_is_help=True,
)


@artifact_cli.command("ls")
def list_artifacts(
    workflow_run_id: str = typer.Argument(
        ..., help="The ID of the workflow run to list artifacts for."
    )
):
    typer.echo("Available artifacts:")

    artifacts = artifact.list_artifacts(workflow_run_id)

    if not artifacts:
        typer.echo("  No artifacts found.")
        return

    for name in artifacts:
        typer.echo(f"- {typer.style(name, bold=True)}")


@artifact_cli.command("info")
def artifact_info(
    artifact_id: str = typer.Argument(
        ..., help="The unique identifier tracking hash of the generated asset."
    )
):
    """Display download links, sizing, and origin execution contexts for a specific task artifact."""
    art = artifact.get_artifact(artifact_id=artifact_id)
    typer.echo(
        f"Artifact Name: {art.name} | Task Run Origin: {art.task_run_id} | URL: {art.url}"
    )
