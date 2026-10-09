# Copyright 2026 Scaleway
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import cloudpickle
import os
import uuid

from abc import ABC, abstractmethod
from typing import Optional

from qall.object import (
    TaskRunOutput,
    TaskRunStatus,
)
from qall.registry import BlockRegistry
from qall.runtime.artifact_backend import ArtifactBackend
from qall.runtime.task_executor import TaskRuntimeExecutor
from qall.credential import extract_credentials_from_env


class SubtaskExecutor(ABC):
    @abstractmethod
    def execute_subtask(
        self, parent_task_run_id: str, input_data: dict
    ) -> TaskRunOutput:
        pass


# Exists only to test behavior without relying on the Daemon, development purpose
class LocalSubtaskExecutor(SubtaskExecutor):
    def __init__(
        self,
        task_hash: str,
        registry: BlockRegistry,
        artifact_backend: ArtifactBackend,
    ):
        self.__task_hash = task_hash
        self.__registry = registry
        self.__artifact_backend = artifact_backend

    def execute_subtask(
        self,
        parent_task_run_id: str,
        input_data: dict,
    ) -> TaskRunOutput:
        executor = TaskRuntimeExecutor(
            task_hash=self.__task_hash,
            registry=self.__registry,
            artifact_backend=self.__artifact_backend,
        )
        input_artifact = cloudpickle.dumps(input_data)
        task_output = executor.execute(
            task_run_id=str(uuid.uuid4()),
            input_artifact=input_artifact,
        )

        return TaskRunOutput(
            output_artifact_hash=task_output.output_artifact_hash,
            output_artifact_bytes=task_output.output_artifact_bytes,
            return_code=task_output.return_code,
            stdout=task_output.stdout,
            stderr=task_output.stderr,
        )


class DaemonSubtaskExecutor(SubtaskExecutor):
    def __init__(
        self,
        task_hash: str,
        registry: BlockRegistry,
        daemon_address: str,
        artifact_backend: Optional[ArtifactBackend] = None,
    ):
        self.__task_hash = task_hash
        self.__registry = registry
        self.__daemon_address = daemon_address
        self.__artifact_backend = artifact_backend
        self.__daemon_client = None

    def _get_daemon_client(self):
        if self.__daemon_client is None:
            from qall_daemon_client import GrpcDaemonClient

            token_path = os.environ.get("QALL_TOKEN_PATH", "/run/secrets/qall_token")

            with open(token_path, "r") as f:
                token = f.read().strip()

            self.__daemon_client = GrpcDaemonClient(
                url=self.__daemon_address, token=token
            )
            self.__daemon_client.connect()

        return self.__daemon_client

    def execute_subtask(
        self,
        parent_task_run_id: str,
        input_data: dict,
    ) -> TaskRunOutput:
        daemon_client = self._get_daemon_client()

        input_artifact_hash = None

        if input_data:
            input_artifact_bytes = cloudpickle.dumps(input_data)

            if self.__artifact_backend:
                input_artifact_hash = self.__artifact_backend.upload_artifact(
                    task_run_id=parent_task_run_id,
                    artifact_bytes=input_artifact_bytes,
                )
            else:
                input_artifact_hash = daemon_client.create_artifact(
                    task_run_id=parent_task_run_id,
                    payload=input_artifact_bytes,
                ).hash

        task_run = daemon_client.create_task_run(
            task_hash=self.__task_hash,
            artifact_hash=input_artifact_hash,
            provider_credentials=extract_credentials_from_env(),
        )

        completed_task_run = daemon_client.wait_for_task_run(
            task_run_id=task_run.id,
            timeout=300.0,
        )

        if completed_task_run.status == TaskRunStatus.ERROR:
            return TaskRunOutput(
                output_artifact_hash=None,
                output_artifact_bytes=None,
                return_code=1,
                stdout="",
                stderr=f"Task run {task_run.id} failed with status ERROR",
            )

        artifacts = daemon_client.list_artifacts(task_run_id=task_run.id)
        output_artifact_hash = None
        output_artifact_bytes = None

        if artifacts:
            output_artifact_hash = artifacts[-1].hash
            output_artifact_bytes = daemon_client.download_artifact(
                artifact_hash=output_artifact_hash
            )

        return TaskRunOutput(
            output_artifact_hash=output_artifact_hash,
            output_artifact_bytes=output_artifact_bytes,
            return_code=0,
            stdout="",
            stderr="",
        )

    def close(self):
        if self.__daemon_client:
            self.__daemon_client.close()
            self.__daemon_client = None
