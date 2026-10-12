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

from qall.config import (
    LocalConfiguration,
    get_local_configuration,
    create_default_configuration,
    config_exists,
    create_configuration,
)
from qall.provider import get_provider_client_by_name


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


def freeze_config():
    pass
