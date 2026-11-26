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

from qall.provider import (
    get_provider_client_by_name,
    get_provider_login_credentials,
    get_logged_provider_name,
    login,
    logout,
)


def login_provider(provider_name: str, **kwargs) -> bool:
    provider_client = get_provider_client_by_name(provider_name)

    login_successful = provider_client.login(**kwargs)

    if not login_successful:
        return False

    return login(provider_name.lower(), **kwargs)


def logout_provider() -> str:
    return logout()


def list_resources(
    provider_name: Optional[str] = None,
    local_is_classical: bool = False,
):
    provider_name = provider_name or get_logged_provider_name() or "local"

    available_resources = []

    if local_is_classical:
        provider_client = get_provider_client_by_name("local")
        available_resources.extend(provider_client.list_classical_resources())

        if provider_name == "local":
            available_resources.extend(provider_client.list_quantum_resources())

    if provider_name != "local":
        provider_credentials = get_provider_login_credentials()

        provider_client = get_provider_client_by_name(provider_name)

        if not provider_client.login(provider_credentials):
            raise RuntimeError(
                f"Failed to authenticate against provider '{provider_name}'."
            )

        available_resources.extend(provider_client.list_classical_resources())
        available_resources.extend(provider_client.list_quantum_resources())

    return available_resources
