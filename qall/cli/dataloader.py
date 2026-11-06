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
import sys
import urllib.parse

import typer

from typing import Optional

import qall.core as core

from qall.exceptions import DataloaderError
from qall.object import credential_fields_for_protocol, is_remote_src

from .utils import parse_extra_args

dataloader_cli = typer.Typer(
    name="dataloader",
    help="Manage dataloaders binding an object storage as a virtual POSIX mount point for tasks.",
    no_args_is_help=True,
)


def _warn_missing_host_dependencies(src: str) -> None:
    """Prints a non-fatal warning when a remote dataloader cannot be mounted.

    The check is best-effort: an unreachable Docker engine is reported by
    ``check_dataloader_host_dependencies`` as a failed check (it never raises),
    and any unexpected error is swallowed so ``add``/``update`` stay fast and
    never fail because of it.
    """
    if not is_remote_src(src):
        return
    try:
        report = core.check_dataloader_host_dependencies()
    except Exception:  # noqa: BLE001 - purely advisory
        return
    if report.ok:
        return
    missing = ", ".join(check.name for check in report.missing)
    typer.echo(
        "Warning: missing host dependencies for remote dataloaders "
        f"({missing}). Run `qall dataloader setup` to inspect and install them.",
        err=True,
    )


def _protocol_of(src: str) -> str:
    """Extracts the object-storage protocol (URL scheme) of a dataloader src."""
    return urllib.parse.urlparse(src).scheme


def _scope_label(scope: str) -> str:
    return "global config" if scope == "global" else ".qall.yml (current project)"


def _scope_tag(scope: str) -> str:
    return "(local)" if scope == "local" else "(global)"


# Maximum display width of any ``ls`` table column. Longer cells are truncated
# (with an ellipsis) so the table stays compact and never wraps on a narrow
# terminal -- a wrapped line is what makes the columns look misaligned.
_MAX_LS_COLUMN_WIDTH = 40


def _truncate_cell(value: str, width: int, ellipsis: str = "…") -> str:
    """Cuts ``value`` down to ``width`` characters, appending an ellipsis."""
    if len(value) <= width:
        return value
    return value[: max(0, width - len(ellipsis))] + ellipsis


def _print_columns(
    headers: list[str], rows: list[list[str]], max_width: Optional[int] = None
) -> None:
    """
    Prints ``rows`` as left-aligned columns under ``headers``.

    Every column is padded to the width of its widest cell (header or data), so
    all rows share the same (standardized) column widths. When ``max_width`` is
    given, no column grows wider than it: over-long cells are truncated (with an
    ellipsis) so the table never wraps on a narrow terminal.
    """
    cells = [headers] + [list(map(str, row)) for row in rows]
    widths = []
    for i in range(len(headers)):
        width = max(len(cell[i]) for cell in cells)
        widths.append(width if max_width is None else min(width, max_width))
    for row in cells:
        padded = []
        for cell, width in zip(row, widths):
            text = _truncate_cell(cell, width) if max_width is not None else str(cell)
            padded.append(text.ljust(width))
        typer.echo(" ".join(padded).rstrip())


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
    current_project: bool = typer.Option(
        False,
        "--current-project",
        help="Store the dataloader in the current project's .qall.yml instead "
        "of the machine-wide global config.",
    ),
    no_prompt: bool = typer.Option(
        False, "--no-prompt", help="Never prompt for credentials (automation)."
    ),
):
    """Create, validate and persist a new dataloader."""
    scope = "local" if current_project else "global"
    creds = parse_extra_args(ctx.args)

    if not no_prompt:
        for field in credential_fields_for_protocol(_protocol_of(src)):
            cred_key = field["name"]
            if cred_key in creds and creds[cred_key]:
                continue
            value = typer.prompt(
                field["prompt"],
                hide_input=field.get("hide_input", False),
                default="",
            )
            if value:
                creds[cred_key] = value

    try:
        dataloader = core.add_dataloader(
            name=name,
            src=src,
            dst=dst,
            creds=creds,
            validate=not no_validate,
            scope=scope,
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(
        f"Dataloader {name!r} added "
        f"({dataloader.src} -> {dataloader.dst}) [{_scope_label(scope)}]."
    )
    _warn_missing_host_dependencies(dataloader.src)


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
    current_project: bool = typer.Option(
        False,
        "--current-project",
        help="Update the dataloader scoped to the current project's .qall.yml.",
    ),
    no_prompt: bool = typer.Option(
        False, "--no-prompt", help="Never prompt for credentials (automation)."
    ),
):
    """Update an existing dataloader. Credentials are prompted for by default;
    leaving a prompt empty keeps the currently stored value."""
    current = core.get_dataloader(name)
    if current is None:
        typer.echo(f"No dataloader named {name!r} found.", err=True)
        raise typer.Exit(code=1)
    if current_project and current.scope != "local":
        typer.echo(
            f"No dataloader named {name!r} found in the current project config.",
            err=True,
        )
        raise typer.Exit(code=1)

    protocol = _protocol_of(src) if src else _protocol_of(current.src)
    creds = parse_extra_args(ctx.args)

    if not no_prompt:
        for field in credential_fields_for_protocol(protocol):
            cred_key = field["name"]
            if cred_key in creds and creds[cred_key]:
                continue
            value = typer.prompt(
                field["prompt"],
                hide_input=field.get("hide_input", False),
            )
            if value:
                creds[cred_key] = value
            # empty input -> key omitted -> core keeps the stored value

    creds = {k: v for k, v in creds.items() if v != ""} or None

    try:
        dataloader = core.update_dataloader(
            name=name,
            src=src,
            dst=dst,
            creds=creds,
            validate=not no_validate,
            scope="local" if current_project else None,
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Dataloader {name!r} updated.")
    _warn_missing_host_dependencies(dataloader.src)


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
    """List every defined dataloader (annotated with its scope)."""
    dataloaders = core.list_dataloaders()
    if not dataloaders:
        typer.echo("No dataloader defined.")
        return
    _print_columns(
        headers=["NAME", "SRC", "DST", "SCOPE"],
        rows=[
            [dl.name, dl.src, dl.dst, f"{_scope_tag(dl.scope)}"]
            for dl in sorted(dataloaders, key=lambda dl: dl.name.lower())
        ],
        max_width=_MAX_LS_COLUMN_WIDTH,
    )


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


@dataloader_cli.command("setup")
def dataloader_setup(
    check: bool = typer.Option(
        False,
        "--check",
        help="Only check the host dependencies; never install anything.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Confirm privileged installations (FUSE package, rclone plugin).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report the commands that would run without executing them.",
    ),
):
    """Check (and optionally install) the host dependencies needed by remote dataloaders."""
    try:
        if not check and not yes and not dry_run and sys.stdin.isatty():
            if not typer.confirm(
                "Install the missing host dependencies with elevated privileges?",
                default=False,
            ):
                raise typer.Exit(code=1)
            yes = True
        report = core.setup_dataloader_host_dependencies(
            check_only=check, assume_yes=yes, dry_run=dry_run
        )
    except (DataloaderError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    for dependency in report.checks:
        marker = "✓" if dependency.ok else "✗"
        typer.echo(f"{marker} {dependency.name}  {dependency.detail}")
        if not dependency.ok:
            if dependency.hint:
                typer.echo(f"    hint: {dependency.hint}")
            if dependency.fix:
                typer.echo(f"    fix: {dependency.fix}")

    if report.ok:
        typer.echo("All dataloader host dependencies are satisfied.")
        return

    typer.echo(f"{len(report.missing)} required dependency(ies) missing.")
    raise typer.Exit(code=1)
