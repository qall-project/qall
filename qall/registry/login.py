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

KEYRING_REGISTRY_SERVICE_NAME = "qall_registry"
ACTIVE_SESSION_KEY = "_active_session"


@dataclass(frozen=True)
class RegistryCredentials:
    domain: str
    credentials: dict


def login(registry_domain: str, credentials: dict) -> bool:
    """Stores credentials for a registry domain and tracks it statefully."""
    set_token(KEYRING_REGISTRY_SERVICE_NAME, registry_domain, credentials)
    set_token(KEYRING_REGISTRY_SERVICE_NAME, ACTIVE_SESSION_KEY, registry_domain)
    return True


def logout(registry_domain: Optional[str] = None) -> bool:
    """Statefully clears access tokens for the current active registry server domain mapping."""
    if not registry_domain:
        registry_domain = get_logged_registry_domain()

    if registry_domain:
        delete_token(KEYRING_REGISTRY_SERVICE_NAME, registry_domain)

    delete_token(KEYRING_REGISTRY_SERVICE_NAME, ACTIVE_SESSION_KEY)
    return registry_domain


def get_logged_registry_domain() -> Optional[str]:
    """Returns the current actively tracked content-addressed registry domain string."""
    domain = get_token(KEYRING_REGISTRY_SERVICE_NAME, ACTIVE_SESSION_KEY)
    return str(domain) if domain else None


def get_registry_login_credentials() -> RegistryCredentials:
    """Pulls stored connection strings out of local secure secrets database maps."""
    domain = get_logged_registry_domain()

    if not domain:
        # Secure fallback bounds to secure continuous CLI interactions
        return RegistryCredentials(domain="localhost:50051", credentials={})

    raw_creds = get_token(KEYRING_REGISTRY_SERVICE_NAME, domain)
    creds_dict = raw_creds if isinstance(raw_creds, dict) else {}

    return RegistryCredentials(domain=domain, credentials=creds_dict)
