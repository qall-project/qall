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

import logging
import os
import subprocess

from importlib.resources import files as resource_files
from pathlib import Path
from typing import Iterator, Optional

from qall.config.paths import host_volumes_root

from .base_manager import BaseDaemonManager

logger = logging.getLogger(__name__)

DEFAULT_UNIT_NAME = "qalld"

# Default daemon binary locations baked into the generated systemd units.
SYSTEM_DAEMON_BINARY = Path("/usr/local/bin/qall-daemon")
USER_DAEMON_BINARY = Path.home() / ".local" / "bin" / "qall-daemon"

SYSTEM_BLOCK_REGISTRY_PATH = Path("/var/cache/qall/block-registry")
SYSTEM_ARTIFACT_REGISTRY_PATH = Path("/var/cache/qall/artifact-registry")
USER_BLOCK_REGISTRY_PATH = Path.home() / ".cache" / "qall" / "block-registry"
USER_ARTIFACT_REGISTRY_PATH = Path.home() / ".cache" / "qall" / "artifact-registry"

SYSTEM_UNIT_DIR = Path("/etc/systemd/system")
USER_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"

_SYSTEM_UNIT_TEMPLATE_RESOURCE = "qall-daemon.service"
_USER_UNIT_TEMPLATE_RESOURCE = "qall-daemon.user.service"


def _load_unit_template(resource_name: str) -> str:
    """Read a systemd unit template shipped inside the package data."""
    resource = resource_files("qall") / "data" / "systemd" / resource_name
    return resource.read_text(encoding="utf-8")


def systemd_ctl_args(scope: str) -> list[str]:
    """
    Return the systemctl command prefix for the given scope.
    """
    if scope == "system":
        return ["systemctl"]
    if scope == "user":
        return ["systemctl", "--user"]
    raise ValueError(
        f"Unsupported systemd scope: {scope} (expected 'system' or 'user')"
    )


def systemctl_is_active(ctl: list[str], unit_name: str) -> bool:
    """
    Return True when the systemd unit is active.
    """
    proc = subprocess.run(
        [*ctl, "is-active", "--quiet", unit_name],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


class SystemdDaemonManager(BaseDaemonManager):

    def __init__(
        self,
        grpc_port: int = 50053,
        unit_name: str = DEFAULT_UNIT_NAME,
        scope: str = "user",
        daemon_binary: Optional[str | Path] = None,
        host_block_registry_path: Optional[str | Path] = None,
        host_artifact_registry_path: Optional[str | Path] = None,
        unit_dir: Optional[str | Path] = None,
    ):
        if scope not in ("system", "user"):
            raise ValueError(
                f"Unsupported systemd scope: {scope} (expected 'system' or 'user')"
            )

        self.grpc_port = grpc_port
        self.scope = scope
        self.unit_name = unit_name

        system_scope = scope == "system"
        self.daemon_binary = str(
            daemon_binary
            or (SYSTEM_DAEMON_BINARY if system_scope else USER_DAEMON_BINARY)
        )
        self.host_block_registry_path = str(
            host_block_registry_path
            or (
                SYSTEM_BLOCK_REGISTRY_PATH if system_scope else USER_BLOCK_REGISTRY_PATH
            )
        )
        self.host_artifact_registry_path = str(
            host_artifact_registry_path
            or (
                SYSTEM_ARTIFACT_REGISTRY_PATH
                if system_scope
                else USER_ARTIFACT_REGISTRY_PATH
            )
        )
        self._unit_dir = Path(
            unit_dir or (SYSTEM_UNIT_DIR if system_scope else USER_UNIT_DIR)
        )
        self._ctl = systemd_ctl_args(scope)

        # Canonicalised once: the daemon creates per-(run, dataloader) host
        # directories under this root, so the value baked into the unit must be
        # the real path (macOS: /tmp -> /private/tmp).
        self.host_volumes_root = str(host_volumes_root().resolve())

    @property
    def unit_file(self) -> Path:
        """Path of the systemd unit file describing this daemon."""
        return self._unit_dir / f"{self.unit_name}.service"

    def is_running(self) -> bool:
        """Return True when the systemd unit is active."""
        return systemctl_is_active(self._ctl, self.unit_name)

    def _start_daemon(self) -> None:
        if self.is_running():
            logger.info(f"Qall daemon unit {self.unit_name} is already active.")
            return

        if not self.unit_file.exists():
            raise RuntimeError(
                f"Systemd unit {self.unit_file} does not exist. "
                "Install it first with SystemdDaemonManager.install() "
            )

        logger.info(f"Starting Qall daemon systemd unit {self.unit_name}...")
        proc = subprocess.run(
            [*self._ctl, "start", self.unit_name],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Failed to start systemd unit {self.unit_name}: "
                f"{proc.stderr.strip()}"
            )

    def stop(self) -> None:
        logger.info(f"Stopping Qall daemon systemd unit {self.unit_name}...")
        proc = subprocess.run(
            [*self._ctl, "stop", self.unit_name],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            logger.warning(
                f"systemctl stop {self.unit_name} returned {proc.returncode}: "
                f"{proc.stderr.strip()}"
            )

    def logs(self) -> Optional[Iterator[str]]:
        """
        Stream the journal lines of the systemd unit.
        """
        if not self.is_running():
            return None

        cmd = ["journalctl", "-u", self.unit_name, "-f", "--no-pager", "-o", "cat"]
        if self.scope == "user":
            cmd.insert(1, "--user")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        return iter(proc.stdout)

    def install(self, enable_now: bool = True) -> None:
        """
        Write the systemd unit file, reload the unit manager and enable (and
        optionally start) the daemon.
        For the user scope, linger is enabled so the daemon survives logouts.
        """
        self._unit_dir.mkdir(parents=True, exist_ok=True)
        self._write_unit_file()

        self._systemctl(["daemon-reload"], check=True)

        if self.scope == "user":
            self._enable_linger()

        if enable_now:
            self._systemctl(["enable", "--now", self.unit_name], check=True)
        else:
            self._systemctl(["enable", self.unit_name], check=True)

        logger.info(f"Installed systemd unit {self.unit_file}.")

    def uninstall(self) -> None:
        """
        Stop and disable the daemon, reload the unit manager and remove the
        unit file.
        """
        self._systemctl(["stop", self.unit_name])
        self._systemctl(["disable", self.unit_name])
        self._systemctl(["daemon-reload"], check=True)

        if self.unit_file.exists():
            self.unit_file.unlink()

        logger.info(f"Uninstalled systemd unit {self.unit_file}.")

    def _systemctl(
        self, args: list[str], check: bool = False
    ) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [*self._ctl, *args],
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"systemctl {' '.join(args)} failed: {proc.stderr.strip()}"
            )
        return proc

    def _write_unit_file(self) -> None:
        self.unit_file.write_text(self._unit_file_content())

    def _unit_file_content(self) -> str:
        if self.scope == "system":
            template = _load_unit_template(_SYSTEM_UNIT_TEMPLATE_RESOURCE)
            return template.format(
                user="qall-daemon",
                binary=self.daemon_binary,
                block_registry=self.host_block_registry_path,
                artifact_registry=self.host_artifact_registry_path,
                host_volumes_root=self.host_volumes_root,
            )
        template = _load_unit_template(_USER_UNIT_TEMPLATE_RESOURCE)
        return template.format(
            binary=self.daemon_binary,
            block_registry=self.host_block_registry_path,
            artifact_registry=self.host_artifact_registry_path,
            host_volumes_root=self.host_volumes_root,
        )

    @staticmethod
    def _enable_linger() -> None:
        user = os.environ.get("USER", "")
        logger.info(
            f"Enabling linger for user {user} so the daemon survives logouts..."
        )
        proc = subprocess.run(["loginctl", "enable-linger", user])
        if proc.returncode != 0:
            logger.warning(
                f"loginctl enable-linger {user} failed — the user-scope daemon "
                "will stop at logout."
            )
