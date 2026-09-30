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

from enum import IntEnum


class WorkflowRunStatus(IntEnum):
    UNKNOWN_STATUS = 0
    STARTING = 1
    RUNNING = 2
    DONE = 3
    ERROR = 4


@dataclass(frozen=True)
class WorkflowRun:
    """WorkflowRun represents a run of a workflow.

    Attributes:
        id: The unique identifier of the workflow run.
        name: The name of the workflow run.
        workflow_id: The ID of the workflow that this run belongs to.
        status: The status of the workflow run (e.g., "pending", "running", "completed", "failed").
        created_at: The timestamp when the workflow run was created.
        started_at: The timestamp when the workflow run started.
        finished_at: The timestamp when the workflow run finished (if applicable).
    """

    id: str
    workflow_id: str
    status: WorkflowRunStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
