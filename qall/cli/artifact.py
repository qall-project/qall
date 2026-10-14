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

from typing import Optional

from qall.core import artifact

artifact_cli = typer.Typer(
    name="artifact",
    help="Inspect and download generated execution artifacts.",
    no_args_is_help=True,
)


@artifact_cli.command("ls")
def list_artifacts(
    workflow_run_id: Optional[str] = typer.Argument(
        None, help="The ID of the workflow run to list artifacts for."
    ),
    local: bool = typer.Option(
        False,
        "--local",
        help="List artifacts from the local artifact registry instead.",
    ),
    artifact_dir: str = typer.Option(
        None,
        "--artifact-dir",
        "-d",
        help="Path to the local artifact registry (default: ~/.cache/qall/artifact-registry).",
    ),
):
    if local:
        typer.echo("Available local artifacts:")

        artifacts = artifact.list_local_artifacts(artifact_dir)

        if not artifacts:
            typer.echo("  No artifacts found.")
            return

        for art in artifacts:
            typer.echo(f"- {typer.style(art.hash, bold=True)}")

        return

    if not workflow_run_id:
        typer.echo(
            "Error: workflow_run_id is required unless `--local` is used.",
            err=True,
        )
        raise typer.Exit(code=1)

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
    ),
    local: bool = typer.Option(
        False, "--local", help="Show metadata from the local artifact registry instead."
    ),
    artifact_dir: str = typer.Option(
        None,
        "--artifact-dir",
        "-d",
        help="Path to the local artifact registry (default: ~/.cache/qall/artifact-registry).",
    ),
):
    """Display download links, sizing, and origin execution contexts for a specific task artifact."""
    if local:
        art = artifact.get_local_artifact(
            artifact_id=artifact_id, artifact_registry=artifact_dir
        )
        typer.echo(f"Artifact Hash: {art.hash}")
        typer.echo(f"Size: {art.size} bytes")
        typer.echo(f"Task Run Origin: {art.task_run_id or 'unknown'}")
        typer.echo(f"Created At: {art.created_at or 'unknown'}")
        return

    art = artifact.get_artifact(artifact_id=artifact_id)
    typer.echo(
        f"Artifact Name: {art.name} | Task Run Origin: {art.task_run_id} | URL: {art.url}"
    )


@artifact_cli.command("show")
def artifact_show(
    artifact_id: str = typer.Argument(
        ..., help="The unique identifier tracking hash of the stored asset."
    ),
    local: bool = typer.Option(
        True,
        "--local",
        help="Read the artifact from the local artifact registry.",
    ),
    raw: bool = typer.Option(
        False, "--raw", help="Print raw bytes instead of deserializing the artifact."
    ),
    artifact_dir: str = typer.Option(
        None,
        "--artifact-dir",
        "-d",
        help="Path to the local artifact registry (default: ~/.cache/qall/artifact-registry).",
    ),
):
    """Deserialize a local artifact and print its python repr()."""
    if not local:
        typer.echo(
            "Error: `artifact show` only supports the local artifact registry for now.",
            err=True,
        )
        raise typer.Exit(code=1)

    if raw:
        payload = artifact.read_local_artifact_bytes(artifact_id, artifact_dir)
        typer.echo(repr(payload))
        return

    value = artifact.deserialize_local_artifact(artifact_id, artifact_dir)
    typer.echo(repr(value))
