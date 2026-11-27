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

import datetime
import logging
import uuid

from typing import Optional

from qall.object import (
    WorkflowRun,
    WorkflowRunStatus,
    DaemonStatus,
    WorkflowPlan,
    ExecutionMode,
)
from qall.registry import BlockRegistry, RegistryCredentials
from qall.provider import (
    WorkflowProviderClient,
    ProviderCredentials,
    get_provider_login_credentials,
)
from qall.core.daemon import (
    get_daemon_status,
    run_task,
    start_daemon,
    stop_daemon,
    apply_resource_assignments,
)
from qall.core.dataloader import (
    provision_dataloader_files_for_dag,
    cleanup_dataloader_files,
)

logger = logging.getLogger(__name__)


def create_workflow_run(
    workflow_plan: WorkflowPlan,
    run_input_artifact_hash: Optional[str] = None,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
    auto_start_daemon: bool = False,
) -> tuple[WorkflowRun, Optional[list]]:
    registry = registry_client or BlockRegistry(read_only=True)
    dag = registry.get_workflow_dag(workflow_plan.tag)

    provider_credentials = provider_credentials or get_provider_login_credentials()

    execution_mode = workflow_plan.execution_mode

    if execution_mode is ExecutionMode.unknown:
        raise RuntimeError("Cannot run if unknown execution mode.")

    must_run_locally = execution_mode in [
        ExecutionMode.local,
        ExecutionMode.classical_local_quantum_remote,
    ]
    must_be_logged = execution_mode in [
        ExecutionMode.remote,
        ExecutionMode.classical_local_quantum_remote,
    ]

    if must_be_logged and not provider_credentials:
        raise RuntimeError(
            "You must be logged in to execute workflows remotely. "
            "Run `qall login <provider>` or use `--local`."
        )

    artifacts = None

    if must_run_locally:
        daemon_status = get_daemon_status()
        daemon_is_already_running = daemon_status.status == DaemonStatus.RUNNING

        if not daemon_is_already_running:
            if not auto_start_daemon:
                raise RuntimeError(
                    "No qall daemon running. Start it first, or set auto_start_daemon=True."
                )
            logger.info("Daemon not running. Starting local daemon...")
            start_daemon(detach=True)

        if workflow_plan.task_assignments:
            apply_resource_assignments(
                resource_assignments=workflow_plan.task_assignments
            )

        dataloader_files = provision_dataloader_files_for_dag(dag)

        start = datetime.datetime.now()
        try:
            artifacts = run_task(
                task_hash=dag.root_hash,
                input_artifact=run_input_artifact_hash,
                provider_credentials=provider_credentials,
            )
            stop = datetime.datetime.now()

            workflow_run = WorkflowRun(
                id=str(uuid.uuid4()),
                workflow_id=str(workflow_plan.tag),
                status=WorkflowRunStatus.DONE,
                created_at=start,
                started_at=start,
                finished_at=stop,
            )
        except Exception as e:
            logger.error(f"Error running workflow `{workflow_plan.tag}`: {e}")
            workflow_run = WorkflowRun(
                id=str(uuid.uuid4()),
                workflow_id=str(workflow_plan.tag),
                status=WorkflowRunStatus.ERROR,
                created_at=start,
                started_at=start,
                finished_at=datetime.datetime.now(),
            )
        finally:
            cleanup_dataloader_files(dataloader_files)
            if not daemon_is_already_running and auto_start_daemon:
                stop_daemon()
    else:
        raise NotImplementedError("remote workflow run not implemented yet")

    return workflow_run, artifacts


def get_workflow_run(
    workflow_run_id: str,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
):
    raise NotImplementedError()


def list_workflow_runs(
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
):
    raise NotImplementedError()


def stop_workflow_run(
    workflow_run_id: str,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
):
    raise NotImplementedError()


def fix_workflow_run(
    entrypoint: str,
    workflow_run_id: str,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
) -> WorkflowRun:
    raise NotImplementedError()
