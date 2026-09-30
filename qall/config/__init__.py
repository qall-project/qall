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

from .local_config import LocalConfiguration

_DEFAULT_CONFIG_FILENAME = ".qall.yml"


def get_local_configuration() -> LocalConfiguration:
    return LocalConfiguration.from_yaml_file(_DEFAULT_CONFIG_FILENAME)


def create_default_configuration(provider_name: str) -> LocalConfiguration:
    return LocalConfiguration.create_default_configuration(
        _DEFAULT_CONFIG_FILENAME, provider_name
    )


def config_exists() -> bool:
    path = Path(_DEFAULT_CONFIG_FILENAME)
    return path.exists()
