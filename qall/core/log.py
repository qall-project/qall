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
from datetime import datetime

from qall.object import Log
from qall.provider import (
    WorkflowProviderClient,
    ProviderCredentials,
    get_provider_login_credentials,
    get_provider_client_by_name,
)


def list_logs(
    workflow_run_id: str,
    timestamp: bool = False,
    follow: bool = False,
    tail: int | None = None,
    since: datetime | None = None,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
) -> list[Log]:
    provider_credentials = provider_credentials or get_provider_login_credentials()
    provider_client = provider_client or get_provider_client_by_name(
        provider_credentials.provider
    )

    logs = provider_client.list_logs(workflow_run_id)

    return logs
