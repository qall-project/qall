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
"""Pure unit tests for the dataloader host dependency checks.

No Docker daemon, no network and no host mutation: the Docker client, the
filesystem probes, ``platform`` and ``subprocess`` are all injected.
"""

import pytest

from qall.daemon import dependencies as deps
from qall.exceptions import DataloaderDependencyError


class _FakePlugin:
    def __init__(self, name: str, enabled: bool = True, reference: str = ""):
        self.name = name
        self.enabled = enabled
        self.attrs = {
            "Name": name,
            "Enabled": enabled,
            "PluginReference": reference,
        }


class _FakePlugins:
    def __init__(self, plugins=None):
        self._plugins = list(plugins or [])
        self.installed = []

    def list(self):
        return list(self._plugins)

    def install(self, image, local_name=None):
        self.installed.append((image, local_name))
        self._plugins.append(_FakePlugin(local_name or image, True))


class _FakeClient:
    def __init__(
        self,
        plugins=None,
        arch="amd64",
        ostype="linux",
        security_options=(),
        version_error=None,
    ):
        self.plugins = _FakePlugins(plugins)
        self._arch = arch
        self._ostype = ostype
        self._security_options = list(security_options)
        self._version_error = version_error

    def version(self):
        if self._version_error is not None:
            raise self._version_error
        return {
            "Version": "27.0.0",
            "Arch": self._arch,
            "OSType": self._ostype,
            "Os": self._ostype.capitalize(),
        }

    def info(self):
        return {"SecurityOptions": list(self._security_options)}


def _ok_client(**kwargs):
    # Docker stores ``--alias rclone`` as ``rclone:latest`` (reference.TagNameOnly).
    return _FakeClient(
        plugins=[
            _FakePlugin(
                "rclone:latest",
                reference="docker.io/rclone/docker-volume-rclone:amd64",
            )
        ],
        **kwargs,
    )


@pytest.fixture
def linux(monkeypatch):
    """A healthy Linux host: /dev/fuse, fusermount3 and apt-get available."""
    monkeypatch.setattr(deps, "_read_os_release", lambda: {"ID": "debian"})
    monkeypatch.setattr(deps, "_path_exists", lambda path: path == "/dev/fuse")
    monkeypatch.setattr(
        deps,
        "_which",
        lambda name: (
            f"/usr/bin/{name}" if name in ("fusermount3", "apt-get") else None
        ),
    )


@pytest.fixture
def missing_fuse(monkeypatch):
    monkeypatch.setattr(deps, "_read_os_release", lambda: {"ID": "debian"})
    monkeypatch.setattr(deps, "_path_exists", lambda path: False)
    monkeypatch.setattr(
        deps,
        "_which",
        lambda name: "/usr/bin/apt-get" if name == "apt-get" else None,
    )


def _by_name(report):
    return {check.name: check for check in report.checks}


### Check matrix ###


def test_all_dependencies_ok_on_linux(linux):
    report = deps.check_dataloader_dependencies(client=_ok_client(), platform="Linux")

    assert report.ok
    assert report.missing == []
    checks = _by_name(report)
    assert checks["docker"].ok
    assert checks["rclone-plugin"].ok
    assert checks["fuse"].ok
    assert "installed and enabled" in checks["rclone-plugin"].detail


def test_plugin_matched_by_aliased_name_without_reference(linux):
    """Docker stores ``--alias rclone`` as ``rclone:latest``."""
    client = _FakeClient(plugins=[_FakePlugin("rclone:latest")])
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")

    assert report.ok
    assert _by_name(report)["rclone-plugin"].ok


def test_plugin_matched_by_remote_reference(linux):
    client = _FakeClient(
        plugins=[
            _FakePlugin(
                "some-alias",
                reference="docker.io/rclone/docker-volume-rclone:amd64",
            )
        ]
    )
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")

    assert report.ok
    assert _by_name(report)["rclone-plugin"].ok


def test_missing_fuse(linux, monkeypatch):
    monkeypatch.setattr(deps, "_path_exists", lambda path: False)
    monkeypatch.setattr(
        deps,
        "_which",
        lambda name: "/usr/bin/apt-get" if name == "apt-get" else None,
    )
    report = deps.check_dataloader_dependencies(client=_ok_client(), platform="Linux")

    fuse = _by_name(report)["fuse"]
    assert not report.ok
    assert not fuse.ok
    assert fuse.fixable
    assert fuse.fix == "sudo apt-get install -y fuse3"
    assert "/dev/fuse" in fuse.detail


def test_missing_fuse_is_not_fixable_without_package_manager(linux, monkeypatch):
    monkeypatch.setattr(deps, "_path_exists", lambda path: False)
    monkeypatch.setattr(deps, "_which", lambda name: None)

    report = deps.check_dataloader_dependencies(client=_ok_client(), platform="Linux")
    fuse = _by_name(report)["fuse"]

    assert not fuse.ok
    assert not fuse.fixable
    assert "FUSE 3" in fuse.fix


def test_missing_plugin(linux):
    report = deps.check_dataloader_dependencies(client=_FakeClient(), platform="Linux")
    plugin = _by_name(report)["rclone-plugin"]

    assert not report.ok
    assert not plugin.ok
    assert plugin.fixable
    assert plugin.fix == (
        "docker plugin install rclone/docker-volume-rclone:amd64 "
        "--alias rclone --grant-all-permissions"
    )


def test_plugin_present_but_disabled(linux):
    client = _FakeClient(plugins=[_FakePlugin("rclone", enabled=False)])
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")
    plugin = _by_name(report)["rclone-plugin"]

    assert not plugin.ok
    assert plugin.fixable
    assert plugin.fix == "docker plugin enable rclone"
    assert "disabled" in plugin.detail


def test_plugin_architecture_is_used_in_install_command(linux):
    report = deps.check_dataloader_dependencies(
        client=_FakeClient(arch="arm64"), platform="Linux"
    )
    plugin = _by_name(report)["rclone-plugin"]

    assert "rclone/docker-volume-rclone:arm64" in plugin.fix


def test_unknown_architecture_fails_the_plugin_check(linux):
    client = _FakeClient(plugins=[_FakePlugin("rclone")], arch="ppc64le")
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")
    plugin = _by_name(report)["rclone-plugin"]

    assert not plugin.ok
    assert "architecture is unknown" in plugin.detail
    assert "amd64 and arm64" in plugin.detail


def test_plugin_architecture_mismatch(linux):
    client = _FakeClient(
        plugins=[_FakePlugin("rclone/docker-volume-rclone:arm64")], arch="amd64"
    )
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")
    plugin = _by_name(report)["rclone-plugin"]

    assert not plugin.ok
    assert "arm64" in plugin.detail and "amd64" in plugin.detail
    assert plugin.fix.endswith(":amd64 --alias rclone --grant-all-permissions")


def test_remote_reference_architecture_wins_over_alias_tag(linux):
    client = _FakeClient(
        plugins=[
            _FakePlugin(
                "rclone:latest",
                reference="docker.io/rclone/docker-volume-rclone:arm64",
            )
        ],
        arch="amd64",
    )
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")
    plugin = _by_name(report)["rclone-plugin"]

    assert not plugin.ok
    assert "arm64" in plugin.detail and "amd64" in plugin.detail
    assert plugin.fix.endswith(":amd64 --alias rclone --grant-all-permissions")


def test_rootless_docker_is_reported_as_unsupported(linux):
    client = _FakeClient(security_options=["name=seccomp", "rootless"])
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")
    plugin = _by_name(report)["rclone-plugin"]

    assert not plugin.ok
    assert not plugin.fixable
    assert "Rootless Docker does not support volume plugins" in plugin.hint
    assert "rootful" in plugin.fix


def test_docker_unreachable_yields_a_single_required_check(monkeypatch):
    def _boom():
        raise RuntimeError("Cannot connect to the Docker daemon")

    monkeypatch.setattr(deps, "_default_client", _boom)
    report = deps.check_dataloader_dependencies(platform="Linux")

    assert len(report.checks) == 1
    check = report.checks[0]
    assert check.name == "docker"
    assert check.required and not check.ok
    assert check.fix == "start Docker (or check your docker context)"
    assert not report.ok


def test_client_version_failure_is_reported_as_docker_failure(linux):
    client = _FakeClient(version_error=RuntimeError("connection refused"))
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")

    assert len(report.checks) == 1
    assert report.checks[0].name == "docker"
    assert not report.ok


def test_macos_skips_host_fuse_and_requires_linux_engine(linux):
    report = deps.check_dataloader_dependencies(
        client=_ok_client(ostype="linux"), platform="Darwin"
    )

    assert report.ok
    checks = _by_name(report)
    assert not checks["fuse"].required
    assert checks["fuse"].ok
    assert checks["fuse"].detail == "provided by the Docker Desktop Linux VM"
    assert checks["docker-engine"].ok and checks["docker-engine"].required
    assert not checks["docker-desktop"].required
    assert "/private/tmp" in checks["docker-desktop"].detail


def test_macos_requires_a_linux_engine(linux):
    report = deps.check_dataloader_dependencies(
        client=_ok_client(ostype="windows"), platform="Darwin"
    )

    assert not report.ok
    engine = _by_name(report)["docker-engine"]
    assert not engine.ok and engine.required
    assert "windows" in engine.detail


### Report formatting / raising ###


def test_summary_contains_fix_commands(linux, monkeypatch):
    monkeypatch.setattr(deps, "_path_exists", lambda path: False)
    report = deps.check_dataloader_dependencies(client=_FakeClient(), platform="Linux")
    summary = report.summary()

    assert "sudo apt-get install -y fuse3" in summary
    assert (
        "docker plugin install rclone/docker-volume-rclone:amd64 "
        "--alias rclone --grant-all-permissions" in summary
    )
    assert "required dependency(ies) missing" in summary


def test_raise_for_missing_includes_hints(linux, monkeypatch):
    monkeypatch.setattr(deps, "_path_exists", lambda path: False)
    report = deps.check_dataloader_dependencies(client=_ok_client(), platform="Linux")

    with pytest.raises(DataloaderDependencyError) as raised:
        report.raise_for_missing()

    message = str(raised.value)
    assert "Hint:" in message
    assert "/dev/fuse" in message


def test_raise_for_missing_is_a_noop_when_ok(linux):
    report = deps.check_dataloader_dependencies(client=_ok_client(), platform="Linux")
    report.raise_for_missing()


def test_ensure_is_a_noop_when_everything_is_ok(linux, monkeypatch):
    def _must_not_install(*args, **kwargs):
        raise AssertionError("install must not be called when the report is ok")

    monkeypatch.setattr(deps, "install_dataloader_dependencies", _must_not_install)

    report = deps.ensure_dataloader_dependencies(
        client=_ok_client(), allow_install=True, assume_yes=True
    )

    assert report.ok


### Installation ###


def test_install_requires_assume_yes(linux, monkeypatch):
    calls = []
    monkeypatch.setattr(deps.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    client = _FakeClient()
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")

    with pytest.raises(DataloaderDependencyError) as raised:
        deps.install_dataloader_dependencies(report=report, client=client)

    assert "requires confirmation" in str(raised.value)
    assert "docker plugin install" in str(raised.value)
    assert client.plugins.installed == []
    assert calls == []


def test_install_plugin_with_assume_yes(linux):
    client = _FakeClient()
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")

    result = deps.install_dataloader_dependencies(
        report=report, client=client, assume_yes=True
    )

    expected = [
        "docker",
        "plugin",
        "install",
        "rclone/docker-volume-rclone:amd64",
        "--alias",
        "rclone",
        "--grant-all-permissions",
    ]
    assert result.commands == [expected]
    assert result.installed == ["rclone-plugin"]
    assert "rclone-plugin" not in result.skipped
    assert "docker" in result.skipped and "fuse" in result.skipped
    assert client.plugins.installed == [("rclone/docker-volume-rclone:amd64", "rclone")]


def test_install_fuse_with_assume_yes(linux, monkeypatch):
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append((argv, kwargs))

    monkeypatch.setattr(deps.subprocess, "run", _fake_run)
    monkeypatch.setattr(deps, "_path_exists", lambda path: False)
    client = _ok_client()
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")

    result = deps.install_dataloader_dependencies(
        report=report, client=client, assume_yes=True
    )

    assert calls
    assert calls[0][0] == ["sudo", "apt-get", "install", "-y", "fuse3"]
    assert result.commands == [["sudo", "apt-get", "install", "-y", "fuse3"]]
    assert result.installed == ["fuse"]


def test_install_dry_run_executes_nothing(linux, monkeypatch):
    calls = []
    monkeypatch.setattr(deps.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    client = _FakeClient()
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")

    result = deps.install_dataloader_dependencies(
        report=report, client=client, assume_yes=False, dry_run=True
    )

    assert calls == []
    assert client.plugins.installed == []
    assert result.installed == []
    assert result.commands
    assert result.commands[0][:4] == [
        "docker",
        "plugin",
        "install",
        "rclone/docker-volume-rclone:amd64",
    ]


def test_install_is_idempotent_when_plugin_is_already_enabled(linux):
    client = _ok_client()
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")

    result = deps.install_dataloader_dependencies(
        report=report, client=client, assume_yes=True
    )

    assert result.commands == []
    assert result.installed == []
    assert "rclone-plugin" in result.skipped
    assert client.plugins.installed == []


def test_install_falls_back_to_cli_when_sdk_signature_differs(linux, monkeypatch):
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append((argv, kwargs))

    monkeypatch.setattr(deps.subprocess, "run", _fake_run)
    client = _FakeClient()

    def _unsupported(*args, **kwargs):
        raise TypeError("install() got an unexpected keyword argument 'local_name'")

    client.plugins.install = _unsupported
    report = deps.check_dataloader_dependencies(client=client, platform="Linux")

    result = deps.install_dataloader_dependencies(
        report=report, client=client, assume_yes=True
    )

    expected = [
        "docker",
        "plugin",
        "install",
        "rclone/docker-volume-rclone:amd64",
        "--alias",
        "rclone",
        "--grant-all-permissions",
    ]
    assert calls and calls[0][0] == expected
    assert result.commands == [expected]
