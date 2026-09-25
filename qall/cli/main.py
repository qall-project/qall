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
import logging
import os

from typing import Optional

import qorus.core as core

from .artifact import artifact_cli
from .provider import provider_cli
from .registry import registry_cli
from .log import log_cli
from .workflow import workflow_cli
from .resource import resource_cli
from .checkpoint import checkpoint_cli
from .config import config_cli
from .daemon import daemon_cli
from .task import task_cli
from .worker import worker_cli
from .utils import parse_extra_args

_DEFAULT_LOGGING_LEVEL = logging.INFO

cli = typer.Typer(
    name="qorus",
    help="A python tool for modern hybrid and quantum workflows.",
    no_args_is_help=True,
)

cli.add_typer(workflow_cli)
cli.add_typer(registry_cli)
cli.add_typer(artifact_cli)
cli.add_typer(provider_cli)
cli.add_typer(config_cli)
cli.add_typer(resource_cli)
cli.add_typer(log_cli)
cli.add_typer(daemon_cli)
cli.add_typer(task_cli)
cli.add_typer(worker_cli)
cli.add_typer(checkpoint_cli)


def _setup_logging():
    logging_level_str = os.getenv("QORUS_LOGGING_LEVEL")

    if not logging_level_str and not _DEFAULT_LOGGING_LEVEL:
        return

    if logging_level_str:
        mapping = logging.getLevelNamesMapping()
        logging_level = mapping.get(logging_level_str.upper())
    else:
        logging_level = _DEFAULT_LOGGING_LEVEL

    logging.basicConfig(level=logging_level)


_setup_logging()


@cli.command("run")
def run(
    entrypoint: str = typer.Argument(
        ..., help="Path to the Python script containing tasks."
    ),
    local: bool = typer.Option(
        False, "--local", help="Wether to run locally or remotely"
    ),
    input_artifact_hash: Optional[str] = typer.Option(
        None,
        "--input-artifact-hash",
        help="The artifact's hash the entrypoint task may require to execute.",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        help="Name of the workflow to declare. Script file name if not provided",
    ),
    version: Optional[str] = typer.Option(
        "latest", "--version", "-v", help="Version tag for the target push."
    ),
    profile: Optional[str] = typer.Option(
        None, "--profile", "-p", help="Target configuration profile name."
    ),
):
    """Compile, delta-push, provision hardware and run an arbitrary hybrid workflow script instantly."""
    typer.echo(f"Initiating compilation run for: {entrypoint}")
    run_obj = core.create_workflow_run(
        entrypoint=entrypoint,
        workflow_name=name,
        workflow_version=version,
        profile_name=profile,
        local_only=local,
        input_artifact_hash=input_artifact_hash,
    )
    typer.echo(f"Workflow run ID: {run_obj.id}")


@cli.command("fix")
def fix(
    entrypoint: str = typer.Argument(
        ..., help="Path to the Python script containing tasks."
    ),
):
    run_obj = core.fix_workflow_run(entrypoint=entrypoint)


@cli.command(
    "login", context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def login(
    ctx: typer.Context,  # Typer Context is mandatory to capture extra unkown arguments
    provider_name: str = typer.Argument(
        ..., help="Name of the cloud provider (e.g., scaleway)."
    ),
    registry_domain: str = typer.Argument(
        ..., help="Domain URI of the content-addressed registry server."
    ),
):
    creds = parse_extra_args(ctx.args)

    if not creds:
        typer.echo(
            "Warning: No dynamic credentials flags passed (e.g. --api-key=XYZ).",
            err=True,
        )

    core.login_provider(provider_name=provider_name, credentials=creds)
    core.login_registry(registry_domain=registry_domain, credentials=creds)
    typer.echo("Successfully authenticated against both endpoints.")


@cli.command("logout")
def logout():
    old_provider = core.logout_provider()

    if old_provider:
        typer.echo(f"Dropped provider credentials successfully from {old_provider}")

    old_registry = core.logout_registry()

    if old_registry:
        typer.echo(f"Dropped provider credentials successfully from {old_registry}")

    if not old_provider and not old_registry:
        typer.echo(f"Already logout")
