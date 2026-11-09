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

import importlib
import sys
import textwrap

import pytest
from pathlib import Path
import tempfile

from qall import task, workflow
from qall.specification import TaskSpec
from qall.specification.task import _remove_task_decorator, _task_decorator_names


@pytest.fixture(autouse=True)
def reset_task_state():
    """Ensure every test starts with a clean Task class state."""
    TaskSpec.reset()
    yield
    TaskSpec.reset()


def _load_module(name: str, source: str):
    """Create a physical module from source and load it (pyan/AST need a file)."""
    tmpdir = tempfile.mkdtemp()
    filepath = Path(tmpdir) / f"{name}.py"
    filepath.write_text(textwrap.dedent(source))
    spec = importlib.util.spec_from_file_location(name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


### DECORATOR FORMS ###


def test_bare_task_decorator():
    @task
    def t():
        return 1

    assert isinstance(t, TaskSpec)
    assert t.name == "t"
    assert t.entrypoint is False
    assert t() == 1


def test_called_task_decorator():
    @task()
    def t():
        return 2

    assert isinstance(t, TaskSpec)
    assert t.entrypoint is False
    assert t() == 2


def test_task_decorator_with_kwargs():
    @task(entrypoint=True, requirements=["numpy"], pure=False)
    def t():
        return 3

    assert t.entrypoint is True
    assert t.requirements == ["numpy"]
    assert t.pure is False
    assert t() == 3


def test_bare_workflow_decorator():
    @workflow
    def t():
        return 4

    assert isinstance(t, TaskSpec)
    assert t.entrypoint is True
    assert t() == 4


def test_called_workflow_decorator():
    @workflow()
    def t():
        return 5

    assert t.entrypoint is True
    assert t() == 5


def test_workflow_decorator_with_kwargs():
    @workflow(requirements=["pandas"])
    def t():
        return 6

    assert t.entrypoint is True
    assert t.requirements == ["pandas"]
    assert t() == 6


### SOURCE / DECORATOR STRIPPING ###


def test_source_strips_all_decorator_forms():
    """@task, @task(), @workflow, @qall.task() and aliases leave no decorator in source."""
    mod = _load_module(
        "deco_strip_mod",
        """
        import qall
        from qall import task, workflow
        from qall import task as qtask
        from qall import workflow as qworkflow

        @task
        def a():
            return 1

        @task()
        def b():
            return 2

        @workflow
        def c():
            return 3

        @qall.task()
        def d():
            return 4

        @qtask()
        def e():
            return 5

        @qworkflow()
        def f():
            return 6
        """,
    )

    for spec in [mod.a, mod.b, mod.c, mod.d, mod.e, mod.f]:
        assert isinstance(spec, TaskSpec)
        # Neither "task" nor "workflow" may remain as a decorator in the source.
        for line in spec.source.splitlines():
            assert not line.lstrip().startswith("@")
        assert spec.source.startswith("def ")


def test_remove_task_decorator_plain_and_called():
    source = textwrap.dedent(
        """
        @task
        def a():
            pass

        @task(entrypoint=True)
        def b():
            pass
        """
    )
    out = _remove_task_decorator(source, {"task", "workflow"})
    assert "@task" not in out
    assert out.count("def ") == 2


def test_remove_task_decorator_qualified_and_aliased():
    source = textwrap.dedent(
        """
        @qall.task()
        def a():
            pass

        @qtask
        def b():
            pass

        @my_pkg.workflow(requirements=["x"])
        def c():
            pass
        """
    )
    out = _remove_task_decorator(source, {"task", "workflow", "qtask"})
    assert "qall.task" not in out
    assert "@qtask" not in out
    assert "my_pkg.workflow" not in out
    assert out.count("def ") == 3


def test_remove_task_decorator_preserves_foreign_decorators():
    source = textwrap.dedent(
        """
        @task
        @app.route("/x")
        @functools.wraps(original)
        def a():
            pass
        """
    )
    out = _remove_task_decorator(source, {"task", "workflow"})
    assert "@task" not in out
    # ast.unparse normalizes string quotes to single quotes
    assert "@app.route('/x')" in out
    assert "@functools.wraps(original)" in out
    assert out.count("def ") == 1


def test_remove_task_decorator_preserves_body():
    source = textwrap.dedent(
        """
        @task(entrypoint=True, requirements=["numpy"])
        def a(x):
            # a meaningful comment
            return x * 2
        """
    )
    out = _remove_task_decorator(source, {"task", "workflow"})
    assert "return x * 2" in out
    # ast.unparse does not preserve comments
    assert "# a meaningful comment" not in out


def test_task_decorator_names_detects_aliases():
    mod = _load_module(
        "aliased_mod",
        """
        from qall import task as qtask

        @qtask()
        def f():
            return 1
        """,
    )
    names = _task_decorator_names(mod.f.func)
    assert "qtask" in names
    assert "task" in names
    # the aliased decorator must actually be stripped from the captured source
    assert "qtask" not in mod.f.source


def test_task_decorator_roundtrip_execution():
    """A fully aliased/qualified workflow executes locally and after JSON round-trip."""
    mod = _load_module(
        "roundtrip_mod",
        """
        import qall

        @qall.task()
        def helper(x):
            return x * 3

        @qall.workflow()
        def main():
            return helper(2)
        """,
    )

    assert mod.main() == 6

    restored = TaskSpec.from_json(mod.main.to_json())
    assert restored() == 6
