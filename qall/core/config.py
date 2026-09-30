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
)


def init_config(
    provider_name: Optional[str] = None, erase_exists: bool = False
) -> LocalConfiguration:
    if not erase_exists and config_exists():
        return None

    config = create_default_configuration(provider_name=provider_name)

    return config


def freeze_config():
    pass
