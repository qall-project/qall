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
import json

import pytest
from pathlib import Path
from typer.testing import CliRunner

from qall.object import Dataloader, SECRET_CREDENTIAL_KEYS
from qall.config import dataloader as config_dl
from qall.config.paths import CONFIG_PATH
from qall.core import dataloader as core_dl
from qall.cli.dataloader import dataloader_cli
from qall.credential import credentials as credential_module
from qall.runtime.dataloader import (
    bind_dataloader,
    bind_dataloaders,
    unbind_dataloaders,
    reset,
    _normalize_dst,
    DataloaderPathTraversalError,
)

runner = CliRunner()


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch):
    """Isolates the user config file under a temp path."""
    path = tmp_path / "qall-config.json"
    monkeypatch.setenv("QALL_CONFIG_PATH", str(path))
    return path


@pytest.fixture
def fake_keyring(monkeypatch):
    """In-memory keyring backend, isolated per test."""
    store = {}

    def set_password(service, user, password):
        store[(service, user)] = password

    def get_password(service, user):
        return store.get((service, user))

    def delete_password(service, user):
        store.pop((service, user), None)

    monkeypatch.setattr(credential_module.keyring, "set_password", set_password)
    monkeypatch.setattr(credential_module.keyring, "get_password", get_password)
    monkeypatch.setattr(credential_module.keyring, "delete_password", delete_password)
    return store


@pytest.fixture
def file_src(tmp_path: Path) -> Path:
    """A local object-storage source (file:// protocol) with a few blobs."""
    src = tmp_path / "storage"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "a.txt").write_text("hello dataloader\n")
    (src / "sub" / "b.csv").write_text("x,y\n1,2\n")
    (src / "top.txt").write_text("top\n")
    return src


def test_dataloader_dto_roundtrip():
    dl = Dataloader(
        name="mnist",
        src="s3://my/storage/",
        dst="./mnist/",
        creds={"endpoint": "http://x", "api_key": "secret"},
    )
    restored = Dataloader.from_json(dl.to_json())
    assert restored == dl
    assert restored.redacted().creds == {"endpoint": "http://x", "api_key": "****"}


def test_dataloader_secret_keys():
    assert "api_key" in SECRET_CREDENTIAL_KEYS
    assert Dataloader.is_secret_key("api_key")
    assert Dataloader.is_secret_key("secret_key")
    assert Dataloader.is_secret_key("password")
    assert not Dataloader.is_secret_key("endpoint")
    assert not Dataloader.is_secret_key("project_id")


def test_dataloader_name_validation():
    with pytest.raises(ValueError):
        Dataloader.validate_name("..")
    with pytest.raises(ValueError):
        Dataloader.validate_name("bad name")
    Dataloader.validate_name("my_dataloader-1")


def test_config_path_defaults():
    assert CONFIG_PATH == Path.home() / ".config" / "qall" / "qall-config.json"


def test_ensure_config_bootstraps(config_path: Path):
    assert not config_path.exists()
    path = config_dl.ensure_config()
    assert path == config_path
    assert config_path.exists()
    assert json.loads(config_path.read_text()) == {"dataloaders": {}}
    # Idempotent
    assert config_dl.ensure_config() == config_path


def test_config_save_load(config_path: Path):
    config_dl.save_config({"dataloaders": {"a": {"src": "x", "dst": "y", "creds": {}}}})
    assert config_dl.load_config()["dataloaders"]["a"]["src"] == "x"


def test_obfuscate_and_resolve_secrets(fake_keyring):
    creds = {"endpoint": "http://x", "api_key": "supersecret", "project_id": "p1"}
    config_dl.store_secrets("mnist", creds)
    obfuscated = config_dl.obfuscate_creds("mnist", creds)

    assert obfuscated["api_key"].startswith("keyring://qall_dataloader/mnist/")
    assert obfuscated["endpoint"] == "http://x"

    dl = Dataloader(name="mnist", src="s3://b/", dst="mnist", creds=obfuscated)
    assert config_dl.resolve_secrets(dl)["api_key"] == "supersecret"
    assert config_dl.resolve_secrets(dl)["endpoint"] == "http://x"

    config_dl.delete_secrets("mnist")
    assert fake_keyring == {}


def test_add_get_list_update_remove(config_path: Path, fake_keyring, file_src: Path):
    src = f"file://{file_src}"
    dl = core_dl.add_dataloader("mnist", src, "./mnist/", {"api_key": "s3cret"})
    assert dl.name == "mnist"

    persisted = core_dl.get_dataloader("mnist")
    assert persisted.dst == "./mnist/"
    # secret is obfuscated on disk
    assert persisted.creds["api_key"].startswith("keyring://")

    assert [d.name for d in core_dl.list_dataloaders()] == ["mnist"]

    updated = core_dl.update_dataloader("mnist", dst="pics")
    assert updated.dst == "pics"

    assert core_dl.remove_dataloader("mnist") is True
    assert core_dl.get_dataloader("mnist") is None
    assert core_dl.remove_dataloader("mnist") is False


def test_add_duplicate_raises(config_path: Path, fake_keyring, file_src: Path):
    core_dl.add_dataloader("mnist", f"file://{file_src}", "mnist")
    with pytest.raises(ValueError, match="already exists"):
        core_dl.add_dataloader("mnist", f"file://{file_src}", "mnist2")


def test_add_unreachable_raises(config_path: Path, fake_keyring, tmp_path: Path):
    with pytest.raises(ValueError, match="not reachable"):
        core_dl.add_dataloader("nope", f"file://{tmp_path}/missing", "nope")


def test_get_dataloaders_for_names_unknown(config_path: Path):
    with pytest.raises(ValueError, match="no such dataloader"):
        core_dl.get_dataloaders_for_names(["ghost"])


def test_validate_dataloader(config_path: Path, fake_keyring, file_src: Path):
    core_dl.add_dataloader("mnist", f"file://{file_src}", "mnist")
    assert core_dl.validate_dataloader("mnist") is True


def test_cli_add_ls_info_rm(config_path: Path, fake_keyring, file_src: Path):
    src = f"file://{file_src}"
    res = runner.invoke(
        dataloader_cli,
        ["add", "mnist", src, "./mnist/", "--api-key=supersecret"],
    )
    assert res.exit_code == 0, res.output

    res = runner.invoke(dataloader_cli, ["ls"])
    assert res.exit_code == 0
    assert "mnist" in res.output

    res = runner.invoke(dataloader_cli, ["info", "mnist"])
    assert res.exit_code == 0
    assert "supersecret" not in res.output
    assert "****" in res.output

    res = runner.invoke(dataloader_cli, ["rm", "mnist"])
    assert res.exit_code == 0
    assert core_dl.get_dataloader("mnist") is None


def test_cli_add_unreachable_fails(config_path: Path, fake_keyring, tmp_path: Path):
    res = runner.invoke(
        dataloader_cli, ["add", "nope", f"file://{tmp_path}/missing", "nope"]
    )
    assert res.exit_code != 0


def test_dst_normalization():
    assert _normalize_dst("./my_data/") == "my_data"
    assert _normalize_dst("my_data") == "my_data"
    assert _normalize_dst("/my_data/") == "my_data"
    with pytest.raises(DataloaderPathTraversalError):
        _normalize_dst("../escape")
    with pytest.raises(ValueError):
        _normalize_dst("/")


def test_bind_absolute_dst_is_normalized_relative(file_src: Path):
    """Spec: "/my_data/" is equivalent to "my_data" (relative mount)."""
    from qall.config.paths import TASK_RUNTIME_WORKDIR

    bind_root = TASK_RUNTIME_WORKDIR / "dataloaders"
    # "/some/abs/data/" is absolute; per spec it is normalized to a relative
    # mount inside the runtime dataloaders base, never mounted at the absolute
    # host location.
    mount = bind_dataloader("abs", f"file://{file_src}", "/some/abs/data/")
    assert mount.is_relative_to(bind_root)
    assert mount == bind_root / "some" / "abs" / "data"
    assert not mount.is_relative_to(Path("/some"))
    unbind_dataloaders()
    reset()


def test_build_fs_protocols(file_src: Path):
    from qall.runtime.dataloader import build_fs, _src_root_path
    from fsspec.implementations.dirfs import DirFileSystem

    assert _src_root_path("s3://my/storage/") == "my/storage"
    assert _src_root_path("gcs://my/google/storage") == "my/google/storage"
    assert _src_root_path("az://container/path") == "container/path"
    assert _src_root_path(f"file://{file_src}") == str(file_src)

    assert isinstance(build_fs(f"file://{file_src}"), DirFileSystem)
    assert isinstance(build_fs("s3://my/storage/"), DirFileSystem)
    assert isinstance(build_fs("gcs://my/google/storage"), DirFileSystem)
    assert isinstance(
        build_fs("az://container/path", {"account_name": "a", "account_key": "k"}),
        DirFileSystem,
    )


def test_task_decorator_accepts_dataloaders():
    from qall.sdk.decorator import task

    @task(dataloaders=["mnist"], entrypoint=True)
    def compute(x):
        return x

    assert compute.dataloaders == ["mnist"]
    assert compute.entrypoint is True
