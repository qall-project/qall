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

import logging

from enum import Enum
from typing import Optional
from pathlib import Path

from qall.runtime import (
    TaskRuntimeExecutor,
    WorkerRuntimeExecutor,
    LocalArtifactBackend,
    DaemonArtifactBackend,
)

from qall.object import TaskRunOutput

logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    LOCAL = "local"
    DAEMON = "daemon"


def execute_task(
    task_hash: str,
    task_run_id: str,
    mode: ExecutionMode,
    daemon_address: str,
    block_registry: Optional[Path | str] = None,
    artifact_hash: Optional[str] = None,
    worker_addresses: Optional[list[str]] = None,
) -> TaskRunOutput:
    """
    Execute a task. Made for intra-container execution.
    """

    block_registry: Path = (
        Path().home() / ".cache/qall/block-registry"
        if not block_registry
        else Path(block_registry)
    )

    if mode == ExecutionMode.DAEMON:
        backend = DaemonArtifactBackend(daemon_address)
    else:
        backend = LocalArtifactBackend()

    executor = TaskRuntimeExecutor(
        task_hash=task_hash,
        registry=block_registry,
        artifact_backend=backend,
        daemon_address=daemon_address,
        worker_addresses=worker_addresses,
    )

    task_output: TaskRunOutput = executor.execute(
        task_run_id=task_run_id,
        input_artifact_hash=artifact_hash,
    )

    return task_output


def execute_worker(
    worker_hash: str,
    port: str,
    block_registry: Optional[Path | str] = None,
):
    """
    Execute a task. Made for intra-container execution.
    """

    block_registry: Path = (
        Path().home() / ".cache/qall/block-registry"
        if not block_registry
        else Path(block_registry)
    )

    executor = WorkerRuntimeExecutor(
        worker_hash=worker_hash,
        registry=block_registry,
        port=port,
    )

    executor.execute()

    return None
