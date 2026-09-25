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

from .utils import parse_extra_args

provider_cli = typer.Typer(
    name="provider",
    help="Configure compute provider environments.",
    no_args_is_help=True,
)


@provider_cli.command(
    "login", context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def provider_login(
    ctx: typer.Context,
    provider_name: str = typer.Argument(
        ..., help="Compute provider identity token identifier (e.g., scaleway)."
    ),
):
    """Authenticate the local instance against a provider control plane."""
    creds = parse_extra_args(ctx.args)

    if not creds:
        typer.echo(
            "Warning: No dynamic credentials flags passed (e.g. --api-key=XYZ).",
            err=True,
        )

    core.login_provider(
        provider_name=provider_name,
        credentials=creds,
    )

    typer.echo(f"Provider session initialized for: {provider_name}")


@provider_cli.command("logout")
def provider_logout():
    old_provider = core.logout_provider()

    if old_provider:
        typer.echo(f"Dropped provider credentials successfully from {old_provider}")
    else:
        typer.echo(f"Already logout")
