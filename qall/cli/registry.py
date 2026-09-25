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
import os

import qorus.core as core

from pathlib import Path

from qorus.specification import WorkflowSpec, WorkerSpec

from .utils import parse_extra_args

registry_cli = typer.Typer(
    name="registry",
    help="Interact with containerless content-addressed task registries.",
    no_args_is_help=True,
)


@registry_cli.command("push")
def registry_push(
    file: Path = typer.Argument(
        ..., help="Path to the Python entrypoint script file containing your tasks."
    ),
    local: bool = typer.Option(
        False,
        "--local",
        help="Wether to store in a local block registry or a remote one.",
    ),
    worker: bool = typer.Option(
        False,
        "--worker",
        help="Whether to push a worker spec instead of a workflow spec.",
    ),
    name: bool = typer.Option(
        None,
        "--name",
        "--n",
        help="Name of the registry entry.",
    ),
    version: bool = typer.Option(
        None,
        "--version",
        "--v",
        help="Version of the registry entry.",
    ),
):
    """Statically compile code statements, analyze the DAG, and delta-push missing blocks to the registry."""

    if not os.path.exists(file):
        typer.echo(f"Cannot found file {file}")
        return

    typer.echo(f"Compiling local Merkle DAG elements from script: {file}")

    name = name or file.stem
    version = version or "latest"

    if worker:
        worker_spec = WorkerSpec(file)
        tag, dag = core.push_worker_on_registry(
            worker_spec=worker_spec,
            worker_name=name,
            worker_version=version,
            local_only=local,
        )
    else:
        workflow_spec = WorkflowSpec(file)
        tag, dag = core.push_workflow_on_registry(
            workflow_spec=workflow_spec,
            workflow_name=name,
            workflow_version=version,
            local_only=local,
        )

    typer.echo(f"Registry synchronization push complete: {tag}, {dag}")


@registry_cli.command("pull")
def registry_pull(
    uri: str = typer.Argument(
        ..., help="The canonical target URI formatted as 'name:version' to download."
    )
):
    """Download the full underlying Merkle DAG block graph from a remote registry into the local cache."""
    if ":" not in uri:
        name, version = uri, "latest"
    else:
        name, version = uri.split(":", 1)
    core.pull_from_registry(workflow_name=name, workflow_version=version)
    typer.echo(f"Blocks downloaded and cached locally for URI: {name}:{version}")


@registry_cli.command(
    "login", context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def registry_login(
    ctx: typer.Context,
    registry_domain: str = typer.Argument(
        ..., help="Target registry hostname URL endpoint."
    ),
):
    """Authenticate and store login tokens for a specific content-addressed task registry server."""
    creds = parse_extra_args(ctx.args)

    if not creds:
        typer.echo(
            "Warning: No dynamic credentials flags passed (e.g. --api-key=XYZ).",
            err=True,
        )

    core.login_registry(
        registry_domain=registry_domain,
        credentials=creds,
    )
    typer.echo(
        f"Registry token persistent mapping written for domain: {registry_domain}"
    )


@registry_cli.command("logout")
def registry_logout():
    old_registry = core.logout_registry()

    if old_registry:
        typer.echo(f"Dropped registry credentials successfully from {old_registry}")
    else:
        typer.echo(f"Already logout")


@registry_cli.command("clear")
def registry_clear():
    core.clear_registry()
