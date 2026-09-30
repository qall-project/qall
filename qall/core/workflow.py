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
from typing import Optional

from qall.object import Tag, Workflow, WorkflowRun, ResourceProfile

from qall.registry import (
    RegistryCredentials,
    BlockRegistry,
    get_registry_login_credentials,
)
from qall.provider import (
    WorkflowProviderClient,
    ProviderCredentials,
    get_provider_login_credentials,
    get_provider_client_by_name,
)
from qall.config import get_local_configuration, create_default_configuration


def create_workflow(
    workflow_name: str,
    workflow_version: str,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
    profile: Optional[ResourceProfile] = None,
) -> Workflow:
    provider_credentials = provider_credentials or get_provider_login_credentials()
    if not provider_credentials:
        raise ValueError(
            "Provider credentials not found: authenticate (qall login) or define env variables"
        )
    provider_client = provider_client or get_provider_client_by_name(
        provider_credentials.provider
    )
    local_config = get_local_configuration() or create_default_configuration()
    profile = profile or local_config.get_default_profile()

    registry_client = registry_client or BlockRegistry()
    registry_credentials = registry_credentials or get_registry_login_credentials()
    registry_client.login(registry_credentials)

    tag = Tag(name=workflow_name, version=workflow_version)

    workflow = provider_client.create_workflow(tag, registry_client.domain, profile)

    return workflow


def run_workflow(
    workflow_id: str = None,
    workflow: Workflow = None,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
    **kwargs
) -> WorkflowRun:
    if not workflow_id and not workflow:
        raise ValueError("At least workflow_id or workflow must be provided")

    provider_credentials = provider_credentials or get_provider_login_credentials()
    provider_client = provider_client or get_provider_client_by_name(
        provider_credentials.provider
    )

    workflow = workflow or provider_client.get_workflow(workflow_id)

    workflow_run = provider_client.create_workflow_run(workflow, kwargs)

    if not workflow_run:
        raise RuntimeError("Failed to create workflow run from workflow", workflow.id)

    return workflow_run


def stop_workflow(
    workflow_run_id: str,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
) -> None:
    provider_credentials = provider_credentials or get_provider_login_credentials()
    provider_client = provider_client or get_provider_client_by_name(
        provider_credentials.provider
    )

    provider_client.stop_workflow_run(workflow_run_id)
