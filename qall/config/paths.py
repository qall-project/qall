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

QALL_CACHE_DIR = Path.home() / ".cache" / "qall"
DEFAULT_BLOCK_REGISTRY_PATH = QALL_CACHE_DIR / "block-registry"
DEFAULT_ARTIFACT_REGISTRY_PATH = QALL_CACHE_DIR / "artifact-registry"
QALL_CONFIG_DIR = Path.home() / ".config" / "qall"
CONFIG_PATH = QALL_CONFIG_DIR / "qall-config.yml"  # The global configuration file path
TASK_RUNTIME_WORKDIR = Path("/workdir")  # Where a task starts at.
HOST_VOLUMES_ROOT = Path(
    "/tmp/qall/"
)  # Where you create volumes on your host to bind into tasks (and/or daemon). Useful for unifs/dataloaders for instance.
