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

from qall.object import Tag, TaskDag, WorkerDag
from qall.registry import (
    RegistryCredentials,
    BlockRegistry,
    get_registry_login_credentials,
    login,
    logout,
)

from qall.specification import WorkflowSpec, WorkerSpec


def create_workflow_dag(
    workflow_spec: WorkflowSpec,
    registry_client: Optional[BlockRegistry] = None,
) -> TaskDag:
    registry_client = registry_client or BlockRegistry()
    dag = registry_client.create_workflow_dag(workflow_spec)

    return dag


def push_workflow_on_registry(
    workflow_spec: WorkflowSpec,
    workflow_name: str,
    workflow_version: str,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    local_only: Optional[bool] = False,
) -> tuple[Tag, TaskDag]:
    """
    Converts the given WorkflowSpec object to compatible registry nodes and pushes them to the registry.
    Returns the tag URI of the entrypoint task.
    """

    registry_client = registry_client or BlockRegistry()

    if not local_only:
        registry_credentials = registry_credentials or get_registry_login_credentials()
        registry_client.login(registry_credentials)

    dag = registry_client.create_workflow_dag(workflow_spec)
    tag = Tag(name=workflow_name, version=workflow_version)

    tag_uri = registry_client.push(tag=tag, dag=dag)

    return tag, dag


def create_worker_dag(
    worker_spec: WorkerSpec,
    registry_client: Optional[BlockRegistry] = None,
) -> WorkerDag:
    registry_client = registry_client or BlockRegistry()
    dag = registry_client.create_worker_dag(worker_spec)

    return dag


def push_worker_on_registry(
    worker_spec: WorkerSpec,
    worker_name: str,
    worker_version: str,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    local_only: Optional[bool] = False,
) -> tuple[Tag, WorkerDag]:
    """
    Converts the given WorkerSpec object to compatible registry nodes and pushes them to the registry.
    Returns the tag URI of the entrypoint task.
    """

    registry_client = registry_client or BlockRegistry()

    if not local_only:
        registry_credentials = registry_credentials or get_registry_login_credentials()
        registry_client.login(registry_credentials)

    dag = registry_client.create_worker_dag(worker_spec)
    tag = Tag(name=worker_name, version=worker_version)

    tag_uri = registry_client.push(tag=tag, dag=dag)

    return tag, dag


def pull_from_registry(
    worker_name: str,
    worker_version: str,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
):
    registry_client = registry_client or BlockRegistry()
    registry_credentials = registry_credentials or get_registry_login_credentials()
    registry_client.login(registry_credentials)

    tag = Tag(name=worker_name, version=worker_version)

    registry_client.pull(tag=tag)


def login_registry(registry_domain: str, **kwargs) -> bool:
    return login(registry_domain.lower(), **kwargs)


def logout_registry() -> str:
    return logout()


def clear_registry(registry_client: Optional[BlockRegistry] = None) -> None:
    registry_client = registry_client or BlockRegistry()
    registry_client.clear()
