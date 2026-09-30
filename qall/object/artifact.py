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


@dataclass(frozen=True)
class Artifact:
    """Artifact represents an artifact produced by a task run.

    Attributes:
        name: The name of the artifact.
        id: The ID of the artifact.
        url: The URL where the artifact can be accessed.
        task_run_id: The ID of the task run that produced the artifact.
        created_at: The timestamp when the artifact was created.
    """

    name: str
    url: str
    id: str
    task_run_id: str
    created_at: datetime
