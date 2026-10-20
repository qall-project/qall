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

from qall.config.paths import (
    QALL_CACHE_DIR,
    DEFAULT_BLOCK_REGISTRY_PATH,
    DEFAULT_ARTIFACT_REGISTRY_PATH,
)


def test_default_paths_resolve_to_previous_hardcoded_locations():
    assert QALL_CACHE_DIR == Path.home() / ".cache" / "qall"
    assert (
        DEFAULT_BLOCK_REGISTRY_PATH
        == Path.home() / ".cache" / "qall" / "block-registry"
    )
    assert (
        DEFAULT_ARTIFACT_REGISTRY_PATH
        == Path.home() / ".cache" / "qall" / "artifact-registry"
    )


def test_default_paths_share_cache_dir():
    assert DEFAULT_BLOCK_REGISTRY_PATH.parent == QALL_CACHE_DIR
    assert DEFAULT_ARTIFACT_REGISTRY_PATH.parent == QALL_CACHE_DIR


def test_modules_consume_default_paths_without_cycles():
    from qall.config import paths  # noqa: F401
    from qall.core import daemon, runtime  # noqa: F401
    from qall.daemon import docker_manager  # noqa: F401
    from qall.registry import BlockRegistry  # noqa: F401

    import qall.registry.block_registry as br

    assert br.DEFAULT_BLOCK_REGISTRY_PATH == DEFAULT_BLOCK_REGISTRY_PATH
    assert (
        docker_manager.DEFAULT_ARTIFACT_REGISTRY_PATH == DEFAULT_ARTIFACT_REGISTRY_PATH
    )


def test_registry_defaults_to_single_source_of_truth():
    import qall.registry.block_registry as br

    assert br.BlockRegistry.__init__.__defaults__[0] == DEFAULT_BLOCK_REGISTRY_PATH
