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
from pathlib import Path

from qall.object import WorkflowRun, WorkflowRunStatus
from qall.specification.workflow import WorkflowSpec
from qall.registry import BlockRegistry, RegistryCredentials
from qall.provider import (
    WorkflowProviderClient,
    ProviderCredentials,
    get_provider_client_by_name,
    get_provider_login_credentials,
)
from qall.core.registry import push_workflow_on_registry
from qall.core.workflow import create_workflow, run_workflow, stop_workflow
from qall.core.daemon import get_daemon_status, run_task, start_daemon, stop_daemon
from qall.config import get_local_configuration, create_default_configuration

logger = logging.getLogger(__name__)


def create_workflow_run(
    entrypoint: str,
    workflow_name: Optional[str] = None,
    workflow_version: Optional[str] = None,
    profile_name: Optional[str] = None,
    input_artifact_hash: Optional[str] = None,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
    local_only: bool = False,
    auto_start_daemon: bool = False,
    **kwargs,
) -> WorkflowRun:
    """
    Launches the full Workflow execution lifecycle from the base file definition.
    Parses Workflow and Tasks -> Push to registry -> Provision resources according to the profile
    -> Starts the Workflow -> Execute the Workflow
    """

    workflow_version = workflow_version or "latest"
    workflow_name = workflow_name or Path(entrypoint).stem

    try:
        workflow_spec = WorkflowSpec(entrypoint)
        tag_uri, dag = push_workflow_on_registry(
            workflow_spec=workflow_spec,
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            registry_client=registry_client,
            registry_credentials=registry_credentials,
            local_only=local_only,
        )
    except Exception as e:
        raise RuntimeError(
            "Couldn't push workflow on registry",
            registry_client.remote_domain if registry_client else "local",
            "\nReason:",
            e,
        )

    if local_only:
        daemon_is_already_running = get_daemon_status()
        if not daemon_is_already_running and auto_start_daemon:
            logger.info(
                "Daemon not running. `auto_start_daemon` set to True, starting daemon..."
            )
            start_daemon()
        elif not daemon_is_already_running and not auto_start_daemon:
            raise RuntimeError(
                "No qall daemon running. Start it first, or set auto_start_daemon to True."
            )

        try:
            start = datetime.datetime.now()
            artifacts = run_task(
                task_hash=dag.root_hash, input_artifact_hash=input_artifact_hash
            )
            stop = datetime.datetime.now()

            logger.info(
                "Workflow done. "
                + (
                    f"Generated artifacts:\n\t{str("\n\t".join([str(a) for a in artifacts]))}"
                    if artifacts
                    else "No artifacts generated."
                )
            )

            workflow_run = WorkflowRun(
                str(uuid.uuid4()),
                str(tag_uri),
                status=WorkflowRunStatus.DONE,
                created_at=start,
                started_at=start,
                finished_at=stop,
            )

        except Exception as e:
            logger.error(f"Error running workflow `{entrypoint}`: {e}")
            workflow_run = WorkflowRun(
                str(uuid.uuid4()),
                str(tag_uri),
                status=WorkflowRunStatus.ERROR,
                created_at=start,
                started_at=start,
                finished_at=datetime.datetime.now(),
            )

        finally:
            if not daemon_is_already_running and auto_start_daemon:
                stop_daemon()

    else:
        local_config = get_local_configuration() or create_default_configuration()

        profile = (
            local_config.get_profile(profile_name)
            if profile_name
            else local_config.get_default_profile()
        )

        workflow = create_workflow(
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            registry_client=registry_client,
            registry_credentials=registry_credentials,
            provider_client=provider_client,
            provider_credentials=provider_credentials,
            profile=profile,
        )

        if not workflow:
            raise RuntimeError("Couldn't create workflow from", entrypoint)

        workflow_run = run_workflow(
            workflow=workflow,
            provider_client=provider_client,
            provider_credentials=provider_credentials,
            input_artifact_hash=input_artifact_hash,
            **kwargs,
        )

        if not workflow_run:
            raise RuntimeError(
                "Couldn't create workflow run from workflow", workflow.id
            )

    return workflow_run


def stop_workflow_run(
    workflow_run_id: str,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
):
    provider_credentials = provider_credentials or get_provider_login_credentials()
    provider_client = provider_client or get_provider_client_by_name(
        provider_credentials.provider
    )

    stop_workflow(
        workflow_run_id,
        provider_client=provider_client,
        provider_credentials=provider_credentials,
    )


def fix_workflow_run(
    entrypoint: str,
    workflow_run_id: str,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
) -> WorkflowRun:
    pass
