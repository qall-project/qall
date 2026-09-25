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

from qorus.core.runtime import execute_worker

worker_cli = typer.Typer(
    name="worker",
    help="Manage worker execution engine",
    no_args_is_help=True,
)


@worker_cli.command("run")
def run(
    worker_hash: str,
    port: int = typer.Option(None, "--port", "-p", help="gRPC port for the worker"),
    block_registry: str = typer.Option(
        None,
        "--block-registry",
        "-l",
        help="Local registry directory",
    ),
):
    execute_worker(
        worker_hash=worker_hash,
        port=port,
        block_registry=block_registry,
    )
