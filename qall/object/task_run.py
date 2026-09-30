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

from typing import Optional

from dataclasses import dataclass
from datetime import datetime

from qall_daemon_client.v1.objects import TaskRunStatus


@dataclass(frozen=True)
class TaskRun:
    """TaskRun represents a run of a task in a workflow.

    Attributes:
        id: The unique identifier of the task run.
        name: The name of the task run.
        workflow_run_id: The ID of the workflow run that this task run belongs to.
        status: The status of the task run (e.g., "pending", "running", "completed", "failed").
        created_at: The timestamp when the task run was created.
        started_at: The timestamp when the task run started.
        finished_at: The timestamp when the task run finished (if applicable).
    """

    id: str
    name: str
    workflow_run_id: str
    task_hash: str
    status: TaskRunStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class TaskRunOutput:
    stdout: str
    stderr: str
    return_code: int
    output_artifact_hash: Optional[str]
    output_artifact_bytes: Optional[bytes] = None
