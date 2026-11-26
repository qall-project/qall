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
from pathlib import Path

from typing import Optional, Union

from qall.object import (
    Tag,
    Workflow,
    WorkflowPlan,
    ResourceProfile,
    TaskDag,
    ExecutionMode,
)

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
from qall.core.registry import push_workflow_on_registry
from qall.core.provider import list_resources
from qall.config import (
    get_local_configuration,
    create_default_configuration,
)
from qall.core.config import resolve_active_profile
from qall.resolver import resolve_workflow_resources
from qall.specification.workflow import WorkflowSpec


def build_workflow(
    entrypoint: str,
    workflow_name: Optional[str] = None,
    workflow_version: Optional[str] = None,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    local_only: bool = False,
) -> tuple[Tag, TaskDag]:
    version = workflow_version or "latest"
    name = workflow_name or Path(entrypoint).stem

    try:
        workflow_spec = WorkflowSpec(entrypoint)
        tag, dag = push_workflow_on_registry(
            workflow_spec=workflow_spec,
            workflow_name=name,
            workflow_version=version,
            registry_client=registry_client,
            registry_credentials=registry_credentials,
            local_only=local_only,
        )
    except Exception as e:
        domain = registry_client.remote_domain if registry_client else "local"
        raise RuntimeError(
            f"Couldn't push workflow on registry '{domain}'.\nReason: {e}"
        ) from e

    return tag, dag


def plan_workflow(
    workflow_tag: Tag | str,
    profile_name: Optional[str] = None,
    allowed_cpus: Optional[list[str]] = None,
    allowed_gpus: Optional[list[str]] = None,
    allowed_qpus: Optional[list[str]] = None,
    execution_mode: Union[ExecutionMode, str] = "remote",
) -> WorkflowPlan:
    if isinstance(execution_mode, str):
        execution_mode = ExecutionMode(execution_mode)

    workflow_tag = (
        Tag.parse(workflow_tag) if isinstance(workflow_tag, str) else workflow_tag
    )
    registry = BlockRegistry()
    dag = registry.get_workflow_dag(workflow_tag)

    profile = resolve_active_profile(
        profile_name=profile_name,
        allowed_qpus=allowed_qpus,
        allowed_cpus=allowed_cpus,
        allowed_gpus=allowed_gpus,
    )

    available_resources = list_resources(
        provider_name=profile.provider,
        execution_mode=execution_mode,
    )

    assignments = resolve_workflow_resources(
        task_dag=dag,
        profile=profile,
        available_resources=available_resources,
        registry=registry,
    )

    return WorkflowPlan(
        tag=workflow_tag,
        task_assignments=assignments,
    )


def deploy_workflow(
    workflow_plan: WorkflowPlan,
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

    tag = workflow_plan.tag

    workflow = provider_client.create_workflow(tag, registry_client.domain, profile)

    return workflow


def get_workflow_from_hash(
    root_hash: str,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    local_only: Optional[bool] = False,
) -> Tag:
    registry_client = registry_client or BlockRegistry(read_only=True)

    if not local_only:
        registry_credentials = registry_credentials or get_registry_login_credentials()
        registry_client.login(registry_credentials)

    tag = registry_client.get_workflow_tag_from_hash(root_hash)

    return tag


def get_workflow(
    workflow_id: str,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
) -> Workflow:
    pass


def list_workflows(
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
) -> list[Workflow]:
    pass


def delete_workflow(
    workflow_id: str,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
):
    pass
