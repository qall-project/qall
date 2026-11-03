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
import yaml
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
    """Isolates the global dataloader config (YAML) under a temp path."""
    path = tmp_path / "qall-config.yml"
    monkeypatch.setenv("QALL_CONFIG_PATH", str(path))
    return path


@pytest.fixture
def local_config_path(tmp_path: Path, monkeypatch):
    """Isolates the current-project dataloader config under a temp path."""
    path = tmp_path / ".qall.yml"
    monkeypatch.setenv("QALL_LOCAL_CONFIG_PATH", str(path))
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


def test_dataloader_scope_roundtrip():
    dl = Dataloader(
        name="mnist",
        src="s3://my/storage/",
        dst="./mnist/",
        creds={},
        scope="local",
    )
    restored = Dataloader.from_json(dl.to_json())
    assert restored.scope == "local"
    assert Dataloader(name="defaults", src="x", dst="y").scope == "global"


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


def test_credential_fields_for_protocol():
    from qall.object import credential_fields_for_protocol

    s3 = {f["name"] for f in credential_fields_for_protocol("s3")}
    assert s3 == {"key", "secret", "endpoint_url"}
    assert credential_fields_for_protocol("file") == []
    assert credential_fields_for_protocol("gcs") == []
    assert credential_fields_for_protocol("") == []
    secret_prompt = next(
        f["prompt"]
        for f in credential_fields_for_protocol("s3a")
        if f["name"] == "secret"
    )
    assert secret_prompt == "Secret key"


def test_config_path_defaults():
    assert CONFIG_PATH == Path.home() / ".config" / "qall" / "qall-config.yml"


def test_ensure_config_bootstraps(config_path: Path):
    assert not config_path.exists()
    path = config_dl.ensure_config()
    assert path == config_path
    assert config_path.exists()
    assert yaml.safe_load(config_path.read_text())["dataloaders"] == {}
    # Idempotent
    assert config_dl.ensure_config() == config_path


def test_config_save_load(config_path: Path):
    config_dl.save_config({"dataloaders": {"a": {"src": "x", "dst": "y", "creds": {}}}})
    assert config_dl.load_config()["dataloaders"]["a"]["src"] == "x"


def test_obfuscate_and_resolve_secrets(fake_keyring):
    creds = {"endpoint": "http://x", "api_key": "supersecret", "project_id": "p1"}
    config_dl.store_secrets("global", "mnist", creds)
    obfuscated = config_dl.obfuscate_creds("global", "mnist", creds)

    assert obfuscated["api_key"].startswith("keyring://qall_dataloader/global:mnist/")
    assert obfuscated["endpoint"] == "http://x"

    dl = Dataloader(
        name="mnist", src="s3://b/", dst="mnist", creds=obfuscated, scope="global"
    )
    assert config_dl.resolve_secrets(dl)["api_key"] == "supersecret"
    assert config_dl.resolve_secrets(dl)["endpoint"] == "http://x"

    config_dl.delete_secrets("global", "mnist")
    assert fake_keyring == {}


def test_add_get_list_update_remove(config_path: Path, fake_keyring, file_src: Path):
    src = f"file://{file_src}"
    dl = core_dl.add_dataloader("mnist", src, "./mnist/", {"api_key": "s3cret"})
    assert dl.name == "mnist"
    assert dl.scope == "global"

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


def test_local_precedence_over_global(
    config_path: Path, local_config_path: Path, fake_keyring, file_src: Path
):
    src = f"file://{file_src}"
    core_dl.add_dataloader("mnist", src, "global_dst", scope="global")
    core_dl.add_dataloader("mnist", src, "local_dst", scope="local")

    dl = core_dl.get_dataloader("mnist")
    assert dl.scope == "local"
    assert dl.dst == "local_dst"

    # Local shadows the global one in the merged view too.
    assert [d.scope for d in core_dl.list_dataloaders()] == ["local"]

    specs = core_dl.resolve_dataloader_specs(["mnist"])
    assert specs["mnist"]["dst"] == "local_dst"


def test_global_fallback_when_local_empty(
    config_path: Path, local_config_path: Path, fake_keyring, file_src: Path
):
    src = f"file://{file_src}"
    core_dl.add_dataloader("mnist", src, "global_dst")

    dl = core_dl.get_dataloader("mnist")
    assert dl.scope == "global"
    assert dl.dst == "global_dst"

    # The local config file is NOT created just by resolving.
    assert not local_config_path.exists()


def test_remove_local_leaves_global(
    config_path: Path, local_config_path: Path, fake_keyring, file_src: Path
):
    src = f"file://{file_src}"
    core_dl.add_dataloader("mnist", src, "global_dst", scope="global")
    core_dl.add_dataloader("mnist", src, "local_dst", scope="local")

    assert core_dl.remove_dataloader("mnist") is True
    # The local shadow was removed; the global entry is visible again.
    dl = core_dl.get_dataloader("mnist")
    assert dl is not None
    assert dl.scope == "global"
    assert dl.dst == "global_dst"


def test_update_merges_creds_keeping_omitted(
    config_path: Path, fake_keyring, file_src: Path
):
    src = f"file://{file_src}"
    core_dl.add_dataloader("mnist", src, "mnist", {"api_key": "old_secret"})

    # Empty prompts simply omit the key: the stored secret is kept.
    updated = core_dl.update_dataloader("mnist", creds={"endpoint": "http://new"})
    resolved = config_dl.resolve_secrets(updated)
    assert resolved["api_key"] == "old_secret"
    assert resolved["endpoint"] == "http://new"


def test_migrate_legacy_global_config(
    config_path: Path, fake_keyring, monkeypatch, tmp_path: Path
):
    legacy = tmp_path / "legacy" / "qall-config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps(
            {
                "dataloaders": {
                    "mnist": {
                        "src": "s3://bucket/data",
                        "dst": "mnist",
                        "creds": {
                            "endpoint": "http://x",
                            "api_key": "keyring://qall_dataloader/mnist/api_key",
                        },
                    }
                }
            }
        )
    )
    monkeypatch.setattr(config_dl, "LEGACY_CONFIG_PATH", legacy)
    # Legacy keyring secrets were stored under user == dataloader name.
    credential_module.set_token("qall_dataloader", "mnist", {"api_key": "legacysecret"})

    path = config_dl.ensure_config()
    assert path == config_path

    data = config_dl.load_config()
    entry = data["dataloaders"]["mnist"]
    assert entry["src"] == "s3://bucket/data"
    assert entry["creds"]["endpoint"] == "http://x"
    assert entry["creds"]["api_key"].startswith(
        "keyring://qall_dataloader/global:mnist/"
    )

    dl = Dataloader(
        name="mnist",
        src=entry["src"],
        dst=entry["dst"],
        creds=entry["creds"],
        scope="global",
    )
    assert config_dl.resolve_secrets(dl)["api_key"] == "legacysecret"

    # The legacy file is deliberately left in place.
    assert legacy.exists()
    # Idempotent: subsequent calls migrate nothing.
    assert config_dl.ensure_config() == config_path


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
    assert "(global)" in res.output

    res = runner.invoke(dataloader_cli, ["info", "mnist"])
    assert res.exit_code == 0
    assert "supersecret" not in res.output
    assert "****" in res.output
    assert '"scope": "global"' in res.output

    res = runner.invoke(dataloader_cli, ["rm", "mnist"])
    assert res.exit_code == 0
    assert core_dl.get_dataloader("mnist") is None


def test_cli_add_current_project_writes_local_only(
    config_path: Path, local_config_path: Path, fake_keyring, file_src: Path
):
    src = f"file://{file_src}"
    res = runner.invoke(
        dataloader_cli,
        ["add", "team1", src, "./data/", "--current-project"],
    )
    assert res.exit_code == 0, res.output

    assert local_config_path.exists()
    # Global config is untouched by a --current-project add.
    assert not config_path.exists()

    data = yaml.safe_load(local_config_path.read_text())
    assert "team1" in data["dataloaders"]

    dl = core_dl.get_dataloader("team1")
    assert dl is not None
    assert dl.scope == "local"


def test_cli_ls_annotates_scope(
    config_path: Path, local_config_path: Path, fake_keyring, file_src: Path
):
    src = f"file://{file_src}"
    core_dl.add_dataloader("shared", src, "g", scope="global")
    core_dl.add_dataloader("proj", src, "l", scope="local")

    res = runner.invoke(dataloader_cli, ["ls"])
    assert res.exit_code == 0
    assert "(global)" in res.output
    assert "(local)" in res.output


def test_cli_ls_columns_aligned(
    config_path: Path, local_config_path: Path, fake_keyring, file_src: Path
):
    src = f"file://{file_src}"
    core_dl.add_dataloader("shared", src, "g", scope="global")
    core_dl.add_dataloader("proj", src, "longer_dst_name", scope="local")
    core_dl.add_dataloader(
        "paris", "s3://bucket/with/a/deep/path", "d", scope="global", validate=False
    )

    res = runner.invoke(dataloader_cli, ["ls"])
    assert res.exit_code == 0, res.output
    # Skip the qall logger frames on stderr ("[timestamp] LEVEL | ...") that the
    # CliRunner mixes into res.output; keep only the ls table lines.
    lines = [
        line
        for line in res.output.splitlines()
        if line.strip() and not line.startswith("[")
    ]
    assert lines[0].startswith("NAME ")
    assert "SRC" in lines[0] and "DST" in lines[0] and "SCOPE" in lines[0]

    # Column boundaries derived from the header row: every data cell must land
    # on the same offsets, i.e. all rows share the same (standardized) widths.
    bounds = [0, lines[0].index("SRC"), lines[0].index("DST"), lines[0].index("SCOPE")]
    # The src cell may be truncated (long paths are capped), so the contract is
    # checked on name + dst + scope landing on the header-derived offsets.
    expected = {
        dl.name: (dl.dst, f"[{'(local)' if dl.scope == 'local' else '(global)'}]")
        for dl in core_dl.list_dataloaders()
    }
    assert len(lines) - 1 == len(expected)

    for line in lines[1:]:
        name = line[bounds[0] : bounds[1]].strip()
        cols = (line[bounds[2] : bounds[3]].strip(), line[bounds[3] :].strip())
        assert (name, *cols) in {(n, *v) for n, v in expected.items()}


def test_cli_ls_sorted_by_name_and_width_capped(
    config_path: Path, local_config_path: Path, fake_keyring, file_src: Path
):
    src = f"file://{file_src}"
    # Insertion order deliberately differs from alphabetical order.
    core_dl.add_dataloader("zebra", src, "z/", scope="global", validate=False)
    core_dl.add_dataloader("apple", src, "fruit/", scope="global", validate=False)
    core_dl.add_dataloader("Mango", src, "tropical/", scope="local", validate=False)

    res = runner.invoke(dataloader_cli, ["ls"])
    assert res.exit_code == 0, res.output
    lines = [
        line
        for line in res.output.splitlines()
        if line.strip() and not line.startswith("[")
    ]
    header = lines[0]
    src_ix = header.index("SRC")
    dst_ix = header.index("DST")
    scope_ix = header.index("SCOPE")

    # Rows are sorted alphabetically (case-insensitive) by NAME.
    names = [ln[:src_ix].strip() for ln in lines[1:]]
    assert names == ["apple", "Mango", "zebra"]

    # Long source paths are capped so the table never hugs the terminal width.
    assert header.index("DST") - src_ix - 1 == 40
    assert len(header) < 80

    # Trailing-slash dst values (e.g. "fruit/", "tropical/") still line up.
    expected = {
        dl.name: (dl.dst, f"[{'(local)' if dl.scope == 'local' else '(global)'}]")
        for dl in core_dl.list_dataloaders()
    }
    for line in lines[1:]:
        name = line[:src_ix].strip()
        cols = (line[dst_ix:scope_ix].strip(), line[scope_ix:].strip())
        assert (name, *cols) in {(n, *v) for n, v in expected.items()}

    # The width cap keeps every line comfortably under a terminal width, so the
    # table never wraps (wrapped lines are what make columns look misaligned).
    assert max(len(ln) for ln in lines) < 80


def test_cli_add_prompts_for_missing_creds(
    config_path: Path, fake_keyring, monkeypatch
):
    prompts = []

    def fake_prompt(prompt, **kwargs):
        prompts.append(prompt)
        return f"value-{len(prompts)}"

    monkeypatch.setattr("typer.prompt", fake_prompt)

    res = runner.invoke(
        dataloader_cli,
        ["add", "mnist", "s3://bucket/data", "./data/", "--no-validate"],
    )
    assert res.exit_code == 0, res.output
    assert "Access key" in prompts
    assert "Secret key" in prompts
    assert any("Endpoint URL" in p for p in prompts)

    dl = core_dl.get_dataloader("mnist")
    assert config_dl.resolve_secrets(dl)["key"] == "value-1"
    assert config_dl.resolve_secrets(dl)["secret"] == "value-2"


def test_cli_add_no_prompt_when_flags_provide_keys(
    config_path: Path, fake_keyring, monkeypatch
):
    def boom(*args, **kwargs):
        raise AssertionError("should not prompt when credentials are flagged")

    monkeypatch.setattr("typer.prompt", boom)

    res = runner.invoke(
        dataloader_cli,
        [
            "add",
            "mnist",
            "s3://bucket/data",
            "./data/",
            "--no-validate",
            "--key=AK",
            "--secret=SK",
            "--endpoint_url=http://x",
        ],
    )
    assert res.exit_code == 0, res.output
    dl = core_dl.get_dataloader("mnist")
    assert config_dl.resolve_secrets(dl)["key"] == "AK"
    assert config_dl.resolve_secrets(dl)["secret"] == "SK"
    assert config_dl.resolve_secrets(dl)["endpoint_url"] == "http://x"


def test_cli_add_no_prompt_never_prompts(config_path: Path, fake_keyring, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("--no-prompt must never call typer.prompt")

    monkeypatch.setattr("typer.prompt", boom)

    res = runner.invoke(
        dataloader_cli,
        ["add", "mnist", "s3://bucket/data", "./data/", "--no-validate", "--no-prompt"],
    )
    assert res.exit_code == 0, res.output


def test_cli_update_empty_prompt_keeps_stored_creds(
    config_path: Path, fake_keyring, monkeypatch
):
    core_dl.add_dataloader(
        "mnist",
        "s3://bucket/data",
        "mnist",
        {"key": "AK", "secret": "SK"},
        validate=False,
    )

    def empty_prompt(*args, **kwargs):
        # Simulate the user pressing Enter on every credential prompt.
        return ""

    monkeypatch.setattr("typer.prompt", empty_prompt)

    res = runner.invoke(dataloader_cli, ["update", "mnist", "--dst=pics"])
    assert res.exit_code == 0, res.output

    dl = core_dl.get_dataloader("mnist")
    assert dl.dst == "pics"
    resolved = config_dl.resolve_secrets(dl)
    assert resolved["key"] == "AK"
    assert resolved["secret"] == "SK"


def test_cli_update_current_project_missing_raises(
    config_path: Path, local_config_path: Path, fake_keyring, file_src: Path
):
    src = f"file://{file_src}"
    core_dl.add_dataloader("mnist", src, "mnist", scope="global")

    res = runner.invoke(
        dataloader_cli, ["update", "mnist", "--dst=x", "--current-project"]
    )
    assert res.exit_code != 0
    assert "current project" in res.output


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

    assert _src_root_path(f"file://{file_src}") == str(file_src)
    assert _src_root_path("s3://my/storage/") == "my/storage"
    # Pure URL parsing (no gcsfs/adlfs imports), so these stay unconditional.
    assert _src_root_path("gcs://my/google/storage") == "my/google/storage"
    assert _src_root_path("az://container/path") == "container/path"

    assert isinstance(build_fs(f"file://{file_src}"), DirFileSystem)
    assert isinstance(build_fs("s3://my/storage/"), DirFileSystem)

    # gcsfs / adlfs are optional deps (see the `objects` dependency group in
    # pyproject.toml): skip their protocol probes, don't fail or pass silently,
    # when the provider package is not installed.
    pytest.importorskip("gcsfs", reason="gcsfs is not installed")
    assert isinstance(build_fs("gcs://my/google/storage"), DirFileSystem)

    pytest.importorskip("adlfs", reason="adlfs is not installed")
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
