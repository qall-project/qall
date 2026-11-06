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
import os

from pathlib import Path

QALL_CACHE_DIR = Path.home() / ".cache" / "qall"
DEFAULT_BLOCK_REGISTRY_PATH = QALL_CACHE_DIR / "block-registry"
DEFAULT_ARTIFACT_REGISTRY_PATH = QALL_CACHE_DIR / "artifact-registry"
QALL_CONFIG_DIR = Path.home() / ".config" / "qall"
CONFIG_PATH = QALL_CONFIG_DIR / "qall-config.yml"  # The global configuration file path
TASK_RUNTIME_WORKDIR = Path("/workdir")  # Where a task starts at.

# Default root under which qall creates host directories bind-mounted into the
# daemon (unifs, dataloaders, ...). It must be a path shared with the Docker
# engine (always true on Linux; Docker Desktop shares /private/tmp on macOS).
DEFAULT_HOST_VOLUMES_ROOT = Path("/tmp/qall")

# Backwards-compatible alias of the default root.
HOST_VOLUMES_ROOT = DEFAULT_HOST_VOLUMES_ROOT


def host_volumes_root() -> Path:
    """
    Root under which qall creates the host directories it bind-mounts into the
    daemon (env-overridable via ``QALL_HOST_VOLUMES_ROOT``).

    Callers must canonicalise the returned path once (``.resolve()``) and reuse
    that exact string everywhere (bind source, bind target, daemon flag) so the
    host, the containerised daemon and the Docker engine all agree on it — on
    macOS ``/tmp`` is a symlink to ``/private/tmp`` and the plugin runs inside
    the Docker Desktop VM.
    """
    override = os.environ.get("QALL_HOST_VOLUMES_ROOT")
    if override:
        return Path(override).expanduser()
    return DEFAULT_HOST_VOLUMES_ROOT
