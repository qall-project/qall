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

resource_cli = typer.Typer(
    name="resource",
    help="Inspect hardware topologies and execution modalities.",
    no_args_is_help=True,
)


@resource_cli.command("ls")
def resource_list():
    """Poll the compute provider to list all accessible CPU, GPU, and physical/emulated QPU hardware."""
    typer.echo("Polling cloud control plane for active available hardware...")
