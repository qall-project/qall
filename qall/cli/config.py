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

import qorus.core as core

config_cli = typer.Typer(
    name="config",
    help="Manage local configuration profile configurations.",
    no_args_is_help=True,
)


@config_cli.command("init")
def config_init(
    provider: Optional[str] = typer.Option(
        "scaleway", "--provider", help="Default target cloud provider name."
    ),
    erase: bool = typer.Option(
        False, "--erase", help="Overwrite existing configuration files if present."
    ),
):
    """Initialize a default .qorus.yml project layout file inside the current directory boundary."""
    res = core.init_config(provider_name=provider, erase_exists=erase)

    if res is None:
        typer.echo("Configuration file already exists. Use --erase to force overwrite.")
    else:
        typer.echo(
            "Project workspace configuration initialized successfully (.qorus.yml)."
        )
