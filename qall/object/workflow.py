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
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .resource import TaskResourceAssignment, ExecutionMode
from .tag import Tag


@dataclass(frozen=True)
class Workflow:
    """Workflow represents a workflow in Qall.

    Attributes:
        id: The unique identifier of the workflow.
        name: The name of the workflow.
        created_at: The timestamp when the workflow was created.
    """

    id: str
    created_at: datetime
    endpoint: str
    name: str
    version: str
    root_task_hash: str
    registry: str
    allowed_resources: list[str]
    resource_allocation_strategy: str


@dataclass(frozen=True)
class WorkflowPlan:
    task_assignments: dict[str, TaskResourceAssignment]
    tag: Tag

    @property
    def execution_mode(self) -> ExecutionMode:
        modes = {a.execution_mode for a in self.task_assignments.values()}
        modes.discard(ExecutionMode.unknown)

        if not modes:
            return ExecutionMode.unknown

        if ExecutionMode.remote in modes:
            return ExecutionMode.remote

        if ExecutionMode.classical_local_quantum_remote in modes:
            return ExecutionMode.classical_local_quantum_remote

        return ExecutionMode.local
