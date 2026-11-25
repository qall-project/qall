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
from typing import List, Optional
from dataclasses import replace

from qall.object import ResourceProfile, AllowedResourceCollection

from qall.config import (
    LocalConfiguration,
    get_local_configuration,
    get_default_configuration,
    create_default_configuration,
    config_exists,
    create_configuration,
)
from qall.provider import (
    get_provider_client_by_name,
    get_provider_login_credentials,
    ProviderCredentials,
)


def init_config(
    provider_name: Optional[str] = None,
    erase_exists: bool = False,
    generate_default_config: bool = True,
) -> LocalConfiguration:
    if not erase_exists and config_exists():
        return get_local_configuration()

    if generate_default_config:
        if provider_name is None or provider_name == "local":
            return create_default_configuration(provider_name=provider_name)
        else:
            provider_client = get_provider_client_by_name(provider_name)

            if not config_exists() or erase_exists:
                config_template = provider_client.get_default_config_template()
                return create_configuration(config_template)

    return None


def override_profile_resources(
    profile: ResourceProfile,
    allowed_qpu: Optional[List[str]] = None,
    allowed_cpu: Optional[List[str]] = None,
    allowed_gpu: Optional[List[str]] = None,
) -> ResourceProfile:
    if not any([allowed_qpu, allowed_cpu, allowed_gpu]):
        return profile

    new_qpu = allowed_qpu if allowed_qpu is not None else profile.allowed.qpu
    new_cpu = allowed_cpu if allowed_cpu is not None else profile.allowed.cpu
    new_gpu = allowed_gpu if allowed_gpu is not None else profile.allowed.gpu

    new_allowed = AllowedResourceCollection(
        qpu=list(new_qpu),
        cpu=list(new_cpu),
        gpu=list(new_gpu),
    )

    return replace(profile, allowed=new_allowed)


def resolve_active_profile(
    profile_name: Optional[str] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
    allowed_qpus: Optional[list[str]] = None,
    allowed_cpus: Optional[list[str]] = None,
    allowed_gpus: Optional[list[str]] = None,
) -> ResourceProfile:
    creds = provider_credentials or get_provider_login_credentials()
    default_provider = creds.provider if creds else "local"

    local_config = (
        get_local_configuration() if config_exists() else init_config(default_provider)
    )

    profile = (
        local_config.get_profile(profile_name)
        if profile_name
        else local_config.get_default_profile()
    )

    if not profile:
        raise RuntimeError(
            f"No profile found (requested: '{profile_name or 'default'}') "
            f"in configuration. Available: {list(local_config.profiles.keys())}"
        )

    if profile.provider != "local" and not creds:
        profile = get_default_configuration("local").get_default_profile()

    return override_profile_resources(
        profile=profile,
        allowed_qpu=allowed_qpus,
        allowed_cpu=allowed_cpus,
        allowed_gpu=allowed_gpus,
    )


def freeze_config():
    pass
