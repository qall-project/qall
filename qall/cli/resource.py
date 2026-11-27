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

import qall.core as core

from qall.object import ExecutionMode
from qall.core.config import resolve_active_profile

from .utils import pretty_resources

resource_cli = typer.Typer(
    name="resource",
    help="Inspect hardware topologies and execution modalities.",
    no_args_is_help=True,
)


@resource_cli.command("ls")
def resource_list(
    profile: Optional[str] = typer.Option(
        None, "--profile", "-p", help="Target configuration profile name."
    ),
    local: bool = typer.Option(
        False, "--local", "-l", help="List local resources only."
    ),
    clocal: bool = typer.Option(
        False,
        "--clocal",
        "-cl",
        help="List classical local resources only and remote quantum resources.",
    ),
):
    """Poll the compute provider to list all accessible CPU, GPU, and physical/emulated QPU hardware."""
    active_profile = resolve_active_profile(
        profile_name=profile,
    )
    provider_name = "local" if local else active_profile.provider

    if local and clocal:
        raise typer.BadParameter("Cannot combine CLI options --local and --clocal")

    execution_mode = ExecutionMode.remote

    if local:
        execution_mode = ExecutionMode.local
    elif clocal:
        execution_mode = ExecutionMode.classical_local_quantum_remote

    resources = core.list_resources(
        provider_name=provider_name,
        execution_mode=execution_mode,
    )

    typer.echo(pretty_resources(resources))
