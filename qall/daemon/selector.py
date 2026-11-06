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

from .base_manager import BaseDaemonManager
from .docker_manager import DockerDaemonManager
from .systemd_manager import SystemdDaemonManager

_SYSTEMD_ONLY_KWARGS = ("scope", "unit_name", "unit_dir")


def get_daemon_manager(
    backend: str | None = None,
    **kwargs,
) -> BaseDaemonManager:
    """
    Build a daemon manager for the requested backend.
    """
    backend = (backend or "docker").lower()

    if backend == "docker":
        docker_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key not in _SYSTEMD_ONLY_KWARGS
        }
        return DockerDaemonManager(**docker_kwargs)
    if backend == "systemd":
        return SystemdDaemonManager(**kwargs)

    raise ValueError(
        f"Unknown daemon backend: {backend!r} (expected 'docker' or 'systemd')"
    )
