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
"""Host dependency checks for dataloader (kernel) mounts.

Dataloaders are mounted into task containers by the daemon through the
**rclone Docker volume plugin**, which itself needs FUSE. This module is the
single place that inspects those host prerequisites and (only on explicit
request) installs them.

Provisioning is **check-only by default**: :func:`check_dataloader_dependencies`
never mutates the host, and :func:`install_dataloader_dependencies` only acts
when the caller passes ``assume_yes=True``. There is no hidden ``input()``
prompting here, so the behaviour is deterministic for the CLI, the SDK and
tests.

The module intentionally imports the Docker SDK lazily (inside
:func:`_default_client`) so importing :mod:`qall` never requires a working
Docker installation.
"""

from __future__ import annotations

import platform as platform_module
import shlex
import shutil
import subprocess

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from qall.exceptions import DataloaderDependencyError
from qall.config.paths import host_volumes_root

# Image of the rclone Docker volume plugin. The install command appends an
# architecture tag (``:amd64`` / ``:arm64``) when the engine architecture is
# known, and falls back to the plain image name otherwise.
DEFAULT_PLUGIN_IMAGE = "rclone/docker-volume-rclone"

# Alias under which the plugin must be enabled for the daemon to create volumes
# with ``--driver rclone``.
PLUGIN_ALIAS = "rclone"

# Architecture tags published for the rclone Docker volume plugin.
_PLUGIN_ARCHITECTURES = frozenset({"amd64", "arm64"})

_MACOS_FUSE_DETAIL = "provided by the Docker Desktop Linux VM"


@dataclass(frozen=True)
class DependencyCheck:
    """Result of a single host prerequisite check.

    ``required`` checks make the whole report fail when ``ok`` is False;
    informational checks (``required=False``) are only surfaced to the user.
    ``fix`` holds the exact command(s) the user can run, while ``fixable`` says
    whether :func:`install_dataloader_dependencies` is able to apply it.
    """

    name: str
    ok: bool
    required: bool
    detail: str
    hint: Optional[str] = None
    fix: Optional[str] = None
    fixable: bool = False


@dataclass
class DependencyReport:
    """Aggregated outcome of every dataloader host dependency check."""

    platform: str
    checks: list[DependencyCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when every *required* check passed."""
        return all(check.ok for check in self.checks if check.required)

    @property
    def missing(self) -> list[DependencyCheck]:
        """Required checks that did not pass, in report order."""
        return [c for c in self.checks if c.required and not c.ok]

    def summary(self) -> str:
        """Returns a multi-line, actionable summary of the report."""
        lines = [f"Dataloader host dependencies ({self.platform}):"]
        for check in self.checks:
            status = "ok" if check.ok else ("missing" if check.required else "warning")
            optional = "" if check.required else " (optional)"
            lines.append(f"  [{status}] {check.name}{optional}: {check.detail}")
            if not check.ok:
                if check.hint:
                    lines.append(f"      hint: {check.hint}")
                if check.fix:
                    lines.append(f"      fix: {check.fix}")
        if self.ok:
            lines.append("All required dataloader host dependencies are satisfied.")
        else:
            lines.append(f"{len(self.missing)} required dependency(ies) missing.")
        return "\n".join(lines)

    def raise_for_missing(self) -> None:
        """Raises :class:`DataloaderDependencyError` when a required check failed."""
        if self.ok:
            return
        hints: list[str] = []
        for check in self.missing:
            if check.hint:
                hints.append(f"{check.name}: {check.hint}")
            if check.fix:
                hints.append(f"{check.name}: run `{check.fix}`")
        raise DataloaderDependencyError(
            self.summary(), hint="\n".join(hints) if hints else None
        )


@dataclass
class InstallResult:
    """Outcome of :func:`install_dataloader_dependencies`.

    ``commands`` always describes the exact argv that was executed, or that
    *would* be executed for a ``dry_run``.
    """

    installed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)


### Injectable helpers (monkeypatched by the unit tests) ###


def _path_exists(path: str) -> bool:
    """Isolated wrapper around :func:`os.path.exists` for testability."""
    return Path(path).exists()


def _which(name: str) -> Optional[str]:
    """Isolated wrapper around :func:`shutil.which` for testability."""
    return shutil.which(name)


def _read_os_release() -> dict[str, str]:
    """Parses ``/etc/os-release`` into a key/value dict (empty when absent)."""
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return {}
    data: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def _default_client() -> Any:
    """Builds a Docker client from the environment (lazy Docker SDK import)."""
    import docker

    return docker.from_env()


### Docker / plugin introspection ###


def _normalise_arch(raw: Any) -> Optional[str]:
    """Maps the engine ``Arch`` value to an rclone plugin tag, if supported."""
    arch = str(raw or "").strip().lower()
    return {
        "amd64": "amd64",
        "x86_64": "amd64",
        "x86-64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
        "arm64/v8": "arm64",
    }.get(arch)


def _engine_arch(version: dict) -> Optional[str]:
    return _normalise_arch(version.get("Arch"))


def _engine_os(version: dict) -> Optional[str]:
    """Returns the engine OS type, preferring ``OSType`` over ``Os``."""
    raw = version.get("OSType") or version.get("Os") or version.get("OsType")
    return str(raw).strip().lower() if raw else None


def _plugin_image(arch: Optional[str]) -> str:
    return f"{DEFAULT_PLUGIN_IMAGE}:{arch}" if arch else DEFAULT_PLUGIN_IMAGE


def _plugin_install_command(arch: Optional[str]) -> str:
    return (
        f"docker plugin install {_plugin_image(arch)} "
        f"--alias {PLUGIN_ALIAS} --grant-all-permissions"
    )


def _plugin_reference(plugin: Any) -> str:
    """Returns the remote image reference (``PluginReference``) of a plugin."""
    attrs = getattr(plugin, "attrs", None) or {}
    reference = attrs.get("PluginReference")
    if reference is None:
        reference = getattr(plugin, "plugin_reference", None)
    return str(reference or "")


def _is_rclone_plugin_name(name: str, reference: str = "") -> bool:
    """Matches the plugin by install alias, image name or remote reference.

    Docker normalises plugin names with ``reference.TagNameOnly``, so an
    install with ``--alias rclone`` is stored as ``rclone:latest``. The remote
    reference (e.g. ``docker.io/rclone/docker-volume-rclone:amd64``) is the
    most reliable identifier when the alias carries a tag.
    """
    name = name.strip().lower()
    if name == PLUGIN_ALIAS or name.startswith(f"{PLUGIN_ALIAS}:"):
        return True
    if name.startswith(DEFAULT_PLUGIN_IMAGE):
        return True
    return DEFAULT_PLUGIN_IMAGE in reference.strip().lower()


def _plugin_tag(name: str, reference: str = "") -> Optional[str]:
    """Returns the *architecture* tag of the plugin image, if discoverable.

    Alias names also carry a tag (``rclone:latest``), which says nothing about
    the architecture. Prefer the remote reference, and only report tags that
    are actual architecture tags.
    """
    for candidate in (reference, name):
        candidate = candidate.strip().lower()
        if DEFAULT_PLUGIN_IMAGE not in candidate or ":" not in candidate:
            continue
        tag = candidate.rsplit(":", 1)[1]
        if tag in _PLUGIN_ARCHITECTURES:
            return tag
    return None


def _is_rootless(info: dict) -> bool:
    options = info.get("SecurityOptions") or []
    return any("rootless" in str(option).lower() for option in options)


def _docker_check(version: dict) -> DependencyCheck:
    details = []
    if version.get("Version"):
        details.append(f"version {version['Version']}")
    if _engine_os(version):
        details.append(f"OS {_engine_os(version)}")
    if version.get("Arch"):
        details.append(f"arch {version['Arch']}")
    suffix = f" ({', '.join(details)})" if details else ""
    return DependencyCheck(
        name="docker",
        ok=True,
        required=True,
        detail=f"Docker engine is reachable{suffix}.",
        hint="Dataloaders are mounted through the Docker engine's rclone volume plugin.",
    )


def _docker_unreachable_check(error: BaseException) -> DependencyCheck:
    return DependencyCheck(
        name="docker",
        ok=False,
        required=True,
        detail=f"Docker is not reachable: {error}",
        hint=(
            "Dataloaders are mounted by the Docker engine through the rclone "
            "volume plugin; the engine must be reachable from this machine."
        ),
        fix="start Docker (or check your docker context)",
    )


def _plugin_check(
    plugins: list[Any],
    arch: Optional[str],
    rootless: bool,
    list_error: Optional[BaseException] = None,
) -> DependencyCheck:
    hint = (
        "The rclone Docker volume plugin is required to mount remote object "
        "storage into task containers."
    )
    if list_error is not None:
        return DependencyCheck(
            name="rclone-plugin",
            ok=False,
            required=True,
            detail=f"Could not list Docker plugins: {list_error}",
            hint=hint,
            fix=_plugin_install_command(arch),
            fixable=not rootless,
        )

    matches = [
        plugin
        for plugin in plugins
        if _is_rclone_plugin_name(
            str(getattr(plugin, "name", "")), _plugin_reference(plugin)
        )
    ]
    # Prefer an enabled match when several versions are installed.
    plugin = next(
        (p for p in matches if getattr(p, "enabled", False)),
        matches[0] if matches else None,
    )

    if plugin is None:
        if rootless:
            return DependencyCheck(
                name="rclone-plugin",
                ok=False,
                required=True,
                detail="rclone Docker volume plugin is not installed.",
                hint=(
                    "Rootless Docker does not support volume plugins; run a "
                    "rootful Docker daemon to use dataloaders."
                ),
                fix=(
                    "Run a rootful Docker daemon (rootless Docker does not "
                    "support the rclone volume plugin)."
                ),
                fixable=False,
            )
        if arch is None:
            detail = (
                "rclone Docker volume plugin is not installed and the engine "
                "architecture is unknown (multi-arch or unsupported value)."
            )
        else:
            detail = "rclone Docker volume plugin is not installed."
        return DependencyCheck(
            name="rclone-plugin",
            ok=False,
            required=True,
            detail=detail,
            hint=hint,
            fix=_plugin_install_command(arch),
            fixable=True,
        )

    if not getattr(plugin, "enabled", False):
        return DependencyCheck(
            name="rclone-plugin",
            ok=False,
            required=True,
            detail="rclone Docker volume plugin is installed but disabled.",
            hint=hint,
            fix=f"docker plugin enable {PLUGIN_ALIAS}",
            fixable=True,
        )

    if arch is None:
        return DependencyCheck(
            name="rclone-plugin",
            ok=False,
            required=True,
            detail=(
                "rclone Docker volume plugin is installed but the engine "
                "architecture is unknown (multi-arch or unsupported value); "
                "the plugin supports amd64 and arm64 only."
            ),
            hint=hint,
            fix=_plugin_install_command(None),
            fixable=True,
        )

    tag = _plugin_tag(str(getattr(plugin, "name", "")), _plugin_reference(plugin))
    if tag is not None and tag != arch:
        return DependencyCheck(
            name="rclone-plugin",
            ok=False,
            required=True,
            detail=(
                f"rclone Docker volume plugin is installed for {tag!r} but the "
                f"engine architecture is {arch!r}."
            ),
            hint=hint,
            fix=_plugin_install_command(arch),
            fixable=True,
        )

    return DependencyCheck(
        name="rclone-plugin",
        ok=True,
        required=True,
        detail=(
            "rclone Docker volume plugin is installed and enabled "
            f"(architecture {arch})."
        ),
        hint=hint,
    )


### FUSE detection ###


_DISTRO_PACKAGE_MANAGERS = (
    (frozenset({"debian", "ubuntu", "linuxmint", "pop"}), "apt-get"),
    (frozenset({"fedora", "rhel", "centos", "rocky", "almalinux"}), "dnf"),
    (frozenset({"arch", "manjaro", "endeavouros"}), "pacman"),
    (
        frozenset(
            {
                "suse",
                "sles",
                "opensuse",
                "opensuse-leap",
                "opensuse-tumbleweed",
            }
        ),
        "zypper",
    ),
)

_PACKAGE_MANAGERS = ("apt-get", "dnf", "pacman", "zypper")

_FUSE_INSTALL_ARGV = {
    "apt-get": ["sudo", "apt-get", "install", "-y", "fuse3"],
    "dnf": ["sudo", "dnf", "install", "-y", "fuse3"],
    "pacman": ["sudo", "pacman", "-S", "--noconfirm", "fuse3"],
    "zypper": ["sudo", "zypper", "install", "-y", "fuse3"],
}

_FUSE_GENERIC_FIX = (
    "Install FUSE 3 (fuse3 / macFUSE) and make sure /dev/fuse is available."
)


def _detect_package_manager(os_release: dict[str, str]) -> Optional[str]:
    """Returns the package manager to use for installing FUSE, if any."""
    ids = {(os_release.get("ID") or "").strip().lower()}
    ids.update((os_release.get("ID_LIKE") or "").strip().lower().split())
    ids.discard("")

    for distro_ids, manager in _DISTRO_PACKAGE_MANAGERS:
        if ids & distro_ids and _which(manager):
            return manager
    # Unknown distro: use whichever supported manager happens to be present.
    for manager in _PACKAGE_MANAGERS:
        if _which(manager):
            return manager
    return None


def _fuse_fix(manager: Optional[str]) -> str:
    if manager is None:
        return _FUSE_GENERIC_FIX
    return " ".join(_FUSE_INSTALL_ARGV[manager])


def _linux_fuse_check() -> DependencyCheck:
    has_device = _path_exists("/dev/fuse")
    fusermount = _which("fusermount3") or _which("fusermount")
    manager = _detect_package_manager(_read_os_release())
    ok = has_device and bool(fusermount)

    missing = []
    if not has_device:
        missing.append("/dev/fuse")
    if not fusermount:
        missing.append("fusermount3/fusermount on PATH")

    if ok:
        detail = "/dev/fuse is available and fusermount3/fusermount is on PATH."
    else:
        detail = "Missing " + " and ".join(missing) + "."

    return DependencyCheck(
        name="fuse",
        ok=ok,
        required=True,
        detail=detail,
        hint=(
            "The rclone volume plugin mounts remote storage through FUSE inside "
            "the Docker engine; /dev/fuse and a fusermount helper are required."
        ),
        fix=_fuse_fix(manager),
        fixable=manager is not None,
    )


def _macos_fuse_check() -> DependencyCheck:
    return DependencyCheck(
        name="fuse",
        ok=True,
        required=False,
        detail=_MACOS_FUSE_DETAIL,
        hint=(
            "On macOS, FUSE lives inside the Docker Desktop Linux VM; no host "
            "package is required."
        ),
    )


def _other_platform_fuse_check(system: str) -> DependencyCheck:
    return DependencyCheck(
        name="fuse",
        ok=True,
        required=False,
        detail=f"not applicable on {system}",
        hint="Dataloader host dependencies are only validated on Linux and macOS.",
    )


def _macos_engine_check(version: dict) -> DependencyCheck:
    engine_os = _engine_os(version)
    return DependencyCheck(
        name="docker-engine",
        ok=engine_os == "linux",
        required=True,
        detail=(
            "Docker engine runs Linux containers."
            if engine_os == "linux"
            else f"Docker engine OS type is {engine_os!r}, expected 'linux'."
        ),
        hint=(
            "Docker Desktop must run Linux containers for the rclone volume "
            "plugin to work on macOS."
        ),
        fix=(
            None
            if engine_os == "linux"
            else "switch Docker Desktop to Linux containers"
        ),
        fixable=False,
    )


def _macos_desktop_check() -> DependencyCheck:
    root = host_volumes_root()
    return DependencyCheck(
        name="docker-desktop",
        ok=True,
        required=False,
        detail=(
            f"Docker Desktop must share {root} with its Linux VM "
            "(/tmp is /private/tmp on macOS)."
        ),
        hint=(
            "Add /tmp (or /private/tmp) to Docker Desktop > Settings > "
            "Resources > File sharing if the daemon cannot create its host "
            "directories."
        ),
    )


### Public API ###


def check_dataloader_dependencies(
    client: Any = None, platform: Optional[str] = None
) -> DependencyReport:
    """Inspects every host prerequisite needed to mount dataloaders.

    ``client`` may be an injected Docker client (duck-typed: it only needs
    ``plugins.list()``, ``version()`` and ``info()``); when omitted a client is
    built with ``docker.from_env()``. ``platform`` overrides
    ``platform.system()`` for testing.

    This function never raises: an unreachable Docker engine is reported as a
    single failing ``docker`` check so callers can print a clean remediation.
    """
    system = platform or platform_module.system()

    try:
        if client is None:
            client = _default_client()
        version = client.version() or {}
    except Exception as error:  # noqa: BLE001 - reported, never raised
        return DependencyReport(
            platform=system, checks=[_docker_unreachable_check(error)]
        )

    try:
        info = client.info() or {}
    except Exception:  # noqa: BLE001 - rootless detection is best-effort
        info = {}

    list_error: Optional[BaseException] = None
    try:
        plugins = list(client.plugins.list())
    except Exception as error:  # noqa: BLE001 - reported through the plugin check
        plugins = []
        list_error = error

    arch = _engine_arch(version)
    rootless = _is_rootless(info)

    checks = [
        _docker_check(version),
        _plugin_check(plugins, arch, rootless, list_error),
    ]

    if system == "Darwin":
        checks.append(_macos_fuse_check())
        checks.append(_macos_engine_check(version))
        checks.append(_macos_desktop_check())
    elif system == "Linux":
        checks.append(_linux_fuse_check())
    else:
        checks.append(_other_platform_fuse_check(system))

    return DependencyReport(platform=system, checks=checks)


def _run(argv: list[str]) -> None:
    """Runs a host-mutating command, converting failures into a clean error."""
    try:
        subprocess.run(argv, check=True, capture_output=True, text=True)
    except PermissionError as error:
        raise DataloaderDependencyError(
            f"Permission denied while running: {' '.join(argv)}",
            hint=(
                "Run the command manually with the required privileges: "
                f"`{' '.join(argv)}`"
            ),
        ) from error
    except subprocess.CalledProcessError as error:
        stderr = (error.stderr or "").strip()
        message = f"Command failed ({error.returncode}): {' '.join(argv)}"
        if stderr:
            message = f"{message}\n{stderr}"
        raise DataloaderDependencyError(
            message,
            hint=f"Run it manually to see the full error: `{' '.join(argv)}`",
        ) from error


def _planned_argv(check: DependencyCheck) -> Optional[list[str]]:
    if not check.fix:
        return None
    return shlex.split(check.fix)


def install_dataloader_dependencies(
    report: Optional[DependencyReport] = None,
    client: Any = None,
    assume_yes: bool = False,
    dry_run: bool = False,
) -> InstallResult:
    """Installs the fixable host dependencies from ``report``.

    Nothing is executed unless ``assume_yes`` is True (installing FUSE and the
    rclone plugin are privileged operations). With ``dry_run`` the exact argv
    that would run is reported in :attr:`InstallResult.commands` but nothing is
    executed and no confirmation is required. Already-satisfied checks are
    listed in :attr:`InstallResult.skipped`.

    Raises :class:`DataloaderDependencyError` when ``assume_yes`` is False and
    at least one action is required, listing the exact commands to run.
    """
    if report is None:
        report = check_dataloader_dependencies(client=client)

    actions = [c for c in report.checks if c.fixable and not c.ok]

    if actions and not assume_yes and not dry_run:
        commands = "\n".join(
            f"  {c.fix}" for c in actions if c.fix is not None
        ) or "\n".join(f"  {c.name}" for c in actions)
        raise DataloaderDependencyError(
            "Installing dataloader host dependencies requires confirmation; "
            "nothing was changed.",
            hint=(
                "Re-run with `--yes` (or assume_yes=True) to apply these "
                f"changes:\n{commands}"
            ),
        )

    result = InstallResult()

    for check in actions:
        argv = _planned_argv(check)
        if argv is None:
            result.skipped.append(check.name)
            continue

        result.commands.append(argv)
        if dry_run:
            continue

        if check.name == "rclone-plugin" and argv[:3] == [
            "docker",
            "plugin",
            "install",
        ]:
            image = argv[3]
            plugin_client = client
            if plugin_client is None:
                try:
                    plugin_client = _default_client()
                except Exception as error:  # noqa: BLE001 - actionable message
                    raise DataloaderDependencyError(
                        f"Docker is not reachable: {error}",
                        hint="start Docker (or check your docker context)",
                    ) from error
            try:
                plugin_client.plugins.install(image, local_name=PLUGIN_ALIAS)
            except (TypeError, AttributeError):
                # Older/newer Docker SDKs may not accept this signature: fall
                # back to the exact CLI command we already advertise.
                _run(argv)
        else:
            _run(argv)

        result.installed.append(check.name)

    if dry_run:
        result.skipped = [c.name for c in report.checks if c.ok or not c.fixable]
    else:
        result.skipped = [
            c.name
            for c in report.checks
            if c.name not in result.installed and not (c.fixable and not c.ok)
        ]

    return result


def ensure_dataloader_dependencies(
    client: Any = None,
    allow_install: bool = False,
    assume_yes: bool = False,
) -> DependencyReport:
    """Ensures every dataloader host dependency is present.

    Returns the (final) report when everything is satisfied. When something is
    missing and ``allow_install`` is True, the fixable dependencies are
    installed (subject to ``assume_yes``) and the host is re-checked. In every
    other case the report raises :class:`DataloaderDependencyError` through
    :meth:`DependencyReport.raise_for_missing`.
    """
    report = check_dataloader_dependencies(client=client)
    if report.ok:
        return report

    if allow_install:
        install_dataloader_dependencies(
            report=report, client=client, assume_yes=assume_yes
        )
        report = check_dataloader_dependencies(client=client)

    report.raise_for_missing()
    return report


__all__ = [
    "DEFAULT_PLUGIN_IMAGE",
    "DependencyCheck",
    "DependencyReport",
    "InstallResult",
    "check_dataloader_dependencies",
    "install_dataloader_dependencies",
    "ensure_dataloader_dependencies",
]
