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
from abc import ABC

from qall.object import (
    Workflow,
    Tag,
    WorkflowRun,
    TaskRun,
    Artifact,
    Checkpoint,
    Resource,
    ResourceProfile,
    Log,
)


class WorkflowProviderClient(ABC):
    def __enter__(self):
        raise NotImplementedError

    def __exit__(self, exc_type, exc_val, exc_tb):
        raise NotImplementedError

    def login(self, credentials: dict) -> bool:
        raise NotImplementedError

    def get_credential_fields(self) -> list[dict]:
        return NotImplementedError

    def get_default_config_template(self) -> str:
        return NotImplementedError

    def create_workflow(
        tag: Tag,
        registry: str,
        profile: ResourceProfile,
    ) -> Workflow:
        raise NotImplementedError

    def get_workflow(self, workflow_id: str) -> Workflow:
        raise NotImplementedError

    def list_workflows(
        self,
    ) -> list[Workflow]:
        raise NotImplementedError

    def delete_workflow(self, workflow_id: str) -> bool:
        raise NotImplementedError

    def create_workflow_run(self, workflow: Workflow, **kwargs) -> WorkflowRun:
        raise NotImplementedError

    def get_workflow_run(self, workflow_run_id: str) -> WorkflowRun:
        raise NotImplementedError

    def list_workflow_runs(self, workflow_id: str) -> list[WorkflowRun]:
        raise NotImplementedError

    def stop_workflow_run(self, workflow_run_id: str) -> WorkflowRun:
        raise NotImplementedError

    def get_artifact(self, artifact_id: str) -> Artifact:
        raise NotImplementedError

    def download_artifact(self, artifact: Artifact) -> str:
        raise NotImplementedError

    def list_artifacts(self, workflow_run_id: str) -> list[Artifact]:
        raise NotImplementedError

    def get_task_run(self, task_run_id: str) -> TaskRun:
        raise NotImplementedError

    def list_task_runs(self, workflow_run_id: str) -> list[TaskRun]:
        raise NotImplementedError

    def stop_task_run(self, task_run_id: str) -> TaskRun:
        raise NotImplementedError

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        raise NotImplementedError

    def list_checkpoints(self, workflow_run_id: str) -> list[Checkpoint]:
        raise NotImplementedError

    def list_resources(self, filters: dict) -> list[Resource]:
        raise NotImplementedError

    def list_logs(self, workflow_run_id: str) -> list[Log]:
        raise NotImplementedError
