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
"""Tests for dataloader mount-point (``dst``) normalisation."""

import pytest

from qall.core import dataloader as core_dl
from qall.object import Dataloader, normalize_dst


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("./my_data/", "my_data"),
        ("/my_data/", "my_data"),
        ("my_data", "my_data"),
        ("a/b", "a/b"),
        ("a//b/", "a/b"),
        ("a\\b", "a/b"),
        (".\\my_data\\", "my_data"),
        ("a/./b", "a/b"),
    ],
)
def test_normalize_dst(raw, expected):
    assert normalize_dst(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "  ",
        "/",
        "//",
        "..",
        "a/../b",
        "../escape",
        "a/..",
        None,
    ],
)
def test_normalize_dst_rejects_invalid_values(raw):
    with pytest.raises(ValueError):
        normalize_dst(raw)


def test_add_dataloader_persists_the_normalised_dst(monkeypatch):
    captured = {}

    monkeypatch.setattr(core_dl, "check_reachable", lambda *a, **k: True)
    monkeypatch.setattr(core_dl, "store_secrets", lambda *a, **k: None)
    monkeypatch.setattr(core_dl, "ensure_config", lambda *a, **k: None)
    monkeypatch.setattr(core_dl, "load_config", lambda *a, **k: {"dataloaders": {}})

    def _save(config, scope="global"):
        captured["config"] = config
        captured["scope"] = scope

    monkeypatch.setattr(core_dl, "save_config", _save)

    dataloader = core_dl.add_dataloader(
        name="mnist", src="s3://bucket/prefix", dst="./my_data/"
    )

    assert dataloader.dst == "my_data"
    assert captured["config"]["dataloaders"]["mnist"]["dst"] == "my_data"
    assert captured["config"]["dataloaders"]["mnist"]["src"] == "s3://bucket/prefix"


def test_add_dataloader_rejects_an_invalid_dst_before_saving(monkeypatch):
    def _must_not_save(*args, **kwargs):
        raise AssertionError("save_config must not be called for an invalid dst")

    monkeypatch.setattr(core_dl, "check_reachable", lambda *a, **k: True)
    monkeypatch.setattr(core_dl, "store_secrets", lambda *a, **k: None)
    monkeypatch.setattr(core_dl, "ensure_config", lambda *a, **k: None)
    monkeypatch.setattr(core_dl, "load_config", lambda *a, **k: {"dataloaders": {}})
    monkeypatch.setattr(core_dl, "save_config", _must_not_save)

    with pytest.raises(ValueError, match="traversal"):
        core_dl.add_dataloader(name="mnist", src="s3://bucket/prefix", dst="a/../b")


def test_update_dataloader_persists_the_normalised_dst(monkeypatch):
    current = Dataloader(
        name="mnist",
        src="s3://bucket/prefix",
        dst="./old/",
        creds={},
        scope="global",
    )
    captured = {}

    monkeypatch.setattr(core_dl, "get_dataloader", lambda name: current)
    monkeypatch.setattr(core_dl, "resolve_secrets", lambda dl: {})
    monkeypatch.setattr(core_dl, "check_reachable", lambda *a, **k: True)
    monkeypatch.setattr(
        core_dl, "load_config", lambda *a, **k: {"dataloaders": {"mnist": {}}}
    )

    def _save(config, scope="global"):
        captured["config"] = config

    monkeypatch.setattr(core_dl, "save_config", _save)

    updated = core_dl.update_dataloader(name="mnist", dst="/new/place/")

    assert updated.dst == "new/place"
    assert captured["config"]["dataloaders"]["mnist"]["dst"] == "new/place"
