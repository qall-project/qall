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
import json

import typer

from typing import Optional

import qall.core as core

from .utils import parse_extra_args

dataloader_cli = typer.Typer(
    name="dataloader",
    help="Manage dataloaders binding an object storage as a virtual POSIX mount point for tasks.",
    no_args_is_help=True,
)


@dataloader_cli.command(
    "add",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def dataloader_add(
    ctx: typer.Context,
    name: str = typer.Argument(
        ..., help="Unique functional identifier of the dataloader."
    ),
    src: str = typer.Argument(
        ..., help="Object storage source (e.g. s3://bucket/prefix/)."
    ),
    dst: str = typer.Argument(
        ..., help="Relative mount point on the task filesystem (e.g. ./my_data/)."
    ),
    no_validate: bool = typer.Option(
        False, "--no-validate", help="Skip the remote reachability check."
    ),
):
    """Create, validate and persist a new dataloader."""
    creds = parse_extra_args(ctx.args)

    try:
        core.add_dataloader(
            name=name,
            src=src,
            dst=dst,
            creds=creds,
            validate=not no_validate,
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Dataloader {name!r} added ({src} -> {dst}).")


@dataloader_cli.command(
    "update",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def dataloader_update(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Name of the dataloader to update."),
    src: Optional[str] = typer.Option(None, "--src", help="New object storage source."),
    dst: Optional[str] = typer.Option(None, "--dst", help="New relative mount point."),
    no_validate: bool = typer.Option(
        False, "--no-validate", help="Skip the remote reachability check."
    ),
):
    """Update an existing dataloader (only provided fields are changed)."""
    creds = parse_extra_args(ctx.args)

    try:
        core.update_dataloader(
            name=name,
            src=src,
            dst=dst,
            creds=creds,
            validate=not no_validate,
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Dataloader {name!r} updated.")


@dataloader_cli.command("rm")
def dataloader_rm(
    name: str = typer.Argument(..., help="Name of the dataloader to remove.")
):
    """Remove a dataloader (config entry and its keyring secrets)."""
    if not core.remove_dataloader(name):
        typer.echo(f"No dataloader named {name!r} found.", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Dataloader {name!r} removed.")


@dataloader_cli.command("ls")
def dataloader_ls():
    """List every defined dataloader."""
    dataloaders = core.list_dataloaders()
    if not dataloaders:
        typer.echo("No dataloader defined.")
        return
    for dl in dataloaders:
        typer.echo(f"{dl.name}\t{dl.src}\t->\t{dl.dst}")


@dataloader_cli.command("info")
def dataloader_info(name: str = typer.Argument(..., help="Name of the dataloader.")):
    """Display a dataloader (sensitive credentials masked)."""
    dl = core.get_dataloader(name)
    if dl is None:
        typer.echo(f"No dataloader named {name!r} found.", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(dl.redacted().to_dict(), indent=2))


@dataloader_cli.command("validate")
def dataloader_validate(
    name: str = typer.Argument(..., help="Name of the dataloader.")
):
    """Re-check that the dataloader source is reachable with its credentials."""
    try:
        ok = core.validate_dataloader(name)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
    if ok:
        typer.echo(f"Dataloader {name!r} is reachable.")
    else:
        typer.echo(f"Dataloader {name!r} is NOT reachable.", err=True)
        raise typer.Exit(code=1)
