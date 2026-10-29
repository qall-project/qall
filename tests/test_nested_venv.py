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

"""
Regression tests for compiling workflows on layouts where the Python virtualenv
is **nested inside** the workflow's directory (common on macOS, e.g.
`<project>/qall-quark/lib/python3.14/site-packages/...`).

Installed packages must never be mistaken for local project files: the pyan3
call graph used to be fed third-party sources (like `docker`) and crash.
"""

import sys
import sysconfig
import tempfile
import textwrap
import types
from pathlib import Path

from qall.specification import WorkflowSpec
from qall.specification.imports import discover_external_imports
from qall.specification import utils


def _nested_venv_site_path(project: Path) -> Path:
    return (
        project
        / "qall-quark"
        / "lib"
        / "python3.14"
        / "site-packages"
        / "docker"
        / "api"
        / "container.py"
    )


def test_is_stdlib_or_site_packages_rejects_nested_venv(tmp_path):
    project = tmp_path / "project"

    # Third-party file inside a venv nested under the project directory…
    assert utils._is_stdlib_or_site_packages(_nested_venv_site_path(project))

    # …and stdlib paths are rejected too.
    assert utils._is_stdlib_or_site_packages(Path(sysconfig.__file__))

    # Genuine local project files are not rejected.
    local_sibling = project / "utils_helper.py"
    assert not utils._is_stdlib_or_site_packages(local_sibling)


def test_module_lives_under_excludes_nested_venv_modules():
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        third_party = types.ModuleType("qall_fake_docker_container")
        third_party.__file__ = str(_nested_venv_site_path(project_dir))
        assert not utils._module_lives_under(third_party, project_dir)

        local = types.ModuleType("qall_fake_local_helper")
        local.__file__ = str(project_dir / "utils_helper.py")
        assert utils._module_lives_under(local, project_dir)


def test_workflow_ignores_modules_from_nested_venv():
    """
    Building a WorkflowSpec must not parse files from a venv nested under the
    workflow's directory. Reproduces the macOS issue where `docker` sources in
    `<project>/qall-quark/lib/python3.14/site-packages` were fed to pyan3.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # A "module" that would be loaded from the nested venv's site-packages.
        fake_module = types.ModuleType("qall_nested_venv_docker")
        fake_module.__file__ = str(_nested_venv_site_path(project_dir))
        sys.modules[fake_module.__name__] = fake_module
        try:
            filepath = project_dir / "main_workflow.py"
            filepath.write_text(textwrap.dedent("""
                    from qall import task, workflow

                    @workflow()
                    def main():
                        return 42
                    """))

            my_wf = WorkflowSpec(filepath, "NestedVenvWorkflow")

            assert my_wf.name == "NestedVenvWorkflow"
            assert len(my_wf.graph.nodes()) == 1
            assert len(my_wf.graph.edges()) == 0
        finally:
            sys.modules.pop(fake_module.__name__, None)


def test_discover_external_imports_skips_nested_venv(tmp_path):
    """
    `discover_external_imports` must not scan an arbitrarily-named virtualenv
    nested inside the project (detected via `pyvenv.cfg`) or its
    site-packages directory: third-party imports from there must not leak into
    the discovered project dependencies.
    """
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("import requests\n")

    venv = project / "qall-quark"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /some/python\n")
    site_packages = venv / "lib" / "python3.14" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "some_dep.py").write_text("import numpy\nimport cv2\n")

    imports = discover_external_imports(project)

    assert "requests" in imports
    assert "numpy" not in imports
    assert "cv2" not in imports
