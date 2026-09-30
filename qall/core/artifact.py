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

from qall.object import Artifact
from qall.provider import (
    WorkflowProviderClient,
    ProviderCredentials,
    get_provider_login_credentials,
    get_provider_client_by_name,
)


def get_artifact(
    artifact_id: str,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
) -> Artifact:
    provider_credentials = provider_credentials or get_provider_login_credentials()
    provider_client = provider_client or get_provider_client_by_name(
        provider_credentials.provider
    )

    artifact = provider_client.get_artifact(artifact_id)

    if not artifact:
        raise RuntimeError("Didn't succeed to get artifact", artifact_id)

    return artifact


def download_artifact(
    artifact_id: str,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
) -> str:
    provider_credentials = provider_credentials or get_provider_login_credentials()
    provider_client = provider_client or get_provider_client_by_name(
        provider_credentials.provider
    )

    artifact = provider_client.get_artifact(artifact_id)

    if not artifact:
        raise RuntimeError("Didn't succeed to get artifact", artifact_id)

    return provider_client.download_artifact(artifact)


def list_artifacts(
    workflow_run_id: str,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
) -> list[Artifact]:
    provider_credentials = provider_credentials or get_provider_login_credentials()
    provider_client = provider_client or get_provider_client_by_name(
        provider_credentials.provider
    )

    return provider_client.list_artifacts(workflow_run_id)
