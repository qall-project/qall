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
from dataclasses import dataclass

from qall.credential import set_token, delete_token, get_token

KEYRING_SERVICE_NAME = "qall_provider"
ACTIVE_SESSION_KEY = "_active_session"


@dataclass(frozen=True)
class ProviderCredentials:
    provider: str
    credentials: dict


def login(provider_name: str, credentials: dict) -> bool:
    """Stores credentials for a provider and registers it as the active session."""
    # Store the core credentials dictionary under the specific provider name entry
    set_token(KEYRING_SERVICE_NAME, provider_name, credentials)
    # Stateful index tracking pointing to the active target
    set_token(KEYRING_SERVICE_NAME, ACTIVE_SESSION_KEY, provider_name)
    return True


def logout(provider_name: Optional[str] = None) -> bool:
    """Statefully drops active provider credentials from local secure keyrings."""
    if not provider_name:
        provider_name = get_logged_provider_name()

    if provider_name:
        delete_token(KEYRING_SERVICE_NAME, provider_name)

    # Clear tracking pointer allocation
    delete_token(KEYRING_SERVICE_NAME, ACTIVE_SESSION_KEY)
    return provider_name


def get_logged_provider_name() -> Optional[str]:
    """Retrieves the active logged provider token key layout name string."""
    name = get_token(KEYRING_SERVICE_NAME, ACTIVE_SESSION_KEY)
    return str(name) if name else None


def get_provider_login_credentials() -> Optional[ProviderCredentials]:
    """Resolves and returns the fully populated credentials of the active session context."""
    provider_name = get_logged_provider_name()
    if not provider_name:
        return None

    raw_creds = get_token(KEYRING_SERVICE_NAME, provider_name)
    creds_dict = raw_creds if isinstance(raw_creds, dict) else {}

    return ProviderCredentials(provider=provider_name, credentials=creds_dict)
