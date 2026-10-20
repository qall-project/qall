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
from datetime import datetime
from functools import partial

import pytest
from pathlib import Path
import tempfile

from qall import task, workflow
from qall.specification import TaskSpec
from qall.specification.imports import (
    discover_file_global_imports,
    map_imports_to_packages,
    merge_requirements,
)
from qall.specification.task import (
    _bundle_local_dependencies,
    _extract_imports_from_function,
)

### FIXTURES ###


@pytest.fixture(autouse=True)
def reset_task_state():
    """Ensure every test starts with a clean Task class state."""
    TaskSpec.reset()
    yield
    TaskSpec.reset()


### TESTS ###


def test_workflow_decorator_and_registration():
    """Test @workflow enforces entrypoint=True and registers with real parent."""

    @workflow()
    def main_pipeline_0():
        pass

    assert isinstance(main_pipeline_0, TaskSpec)
    assert main_pipeline_0.entrypoint is True

    @task(entrypoint=True)
    def main_pipeline_1():
        pass

    assert isinstance(main_pipeline_1, TaskSpec)
    assert main_pipeline_1.entrypoint is True

    @task(entrypoint=False)
    def main_pipeline_2():
        pass

    assert isinstance(main_pipeline_2, TaskSpec)
    assert main_pipeline_2.entrypoint is False


def test_dataclass_initialization():
    """Test that the dataclass properly initializes and parses function source."""

    def sample_func(x):
        return x * 2

    t = TaskSpec(func=sample_func)

    assert t.name == "sample_func"
    assert t.entrypoint is False
    assert "return x * 2" in t.source
    assert t.requirements == []


def test_task_decorator():
    """Test the @task decorator parses kwargs and wraps correctly."""

    deps = ["numpy==2.0", "pandas==15.0"]

    @task(entrypoint=False, requirements=deps)
    def decorated_func():
        return "hello"

    assert isinstance(decorated_func, TaskSpec)
    assert decorated_func.name == "decorated_func"
    assert decorated_func.entrypoint is False
    assert decorated_func.requirements == deps


def test_execution_mode():
    """Test standard execution mode routes to the underlying callable."""

    @task()
    def add(a, b):
        return a + b

    result = add(5, 10)
    assert result == 15


def test_compilation_mode():
    """Test compilation mode returns the Task instance instead of executing."""

    @task()
    def add(a, b):
        return a + b

    TaskSpec.compilation()
    result = add(5, 10)

    # In compilation mode, calling the task returns the task itself (for DAG building)
    assert result is add
    assert isinstance(result, TaskSpec)


def test_switch_mode():
    """Test switching between compilation and execution modes."""

    @task()
    def add(a, b):
        return a + b

    result = add(5, 10)
    TaskSpec.compilation()
    my_task = add(5, 10)

    assert result == 15
    assert isinstance(my_task, TaskSpec)
    assert my_task == add


def test_invalid_mode_raises_error():
    """Test behavior when internal state is corrupted."""

    @task()
    def dummy():
        pass

    TaskSpec._mode = "INVALID_STATE"

    with pytest.raises(RuntimeError, match="is in invalid state"):
        dummy()


def test_serialization_json():
    """Test in-memory serialization logic using cloudpickle."""

    deps = ["numpy"]

    def secret_math(x):

        # A test comment
        return x**2 + 5

    t_original = TaskSpec(func=secret_math, entrypoint=True, requirements=deps)

    payload = t_original.to_json()
    assert isinstance(payload, str)

    t_restored = TaskSpec.from_json(payload)
    assert isinstance(t_restored, TaskSpec)
    assert t_restored.name == "secret_math"
    assert t_restored.entrypoint is True
    assert t_restored.requirements == deps
    assert t_restored(10) == 105


def test_serialization_file():
    """Test writing to and loading from a file path."""

    deps = ["numpy"]

    with tempfile.TemporaryDirectory() as tmpdir:

        filepath = Path(tmpdir) / "task.json"

        assert not filepath.exists()

        @workflow(requirements=deps)
        def secret_math(x):
            # A test comment

            return x**2 + 5

        secret_math.to_file(filepath)

        assert filepath.exists()

        t_restored = TaskSpec.from_file(filepath)

    assert isinstance(t_restored, TaskSpec)
    assert t_restored.name == "secret_math"
    assert t_restored.entrypoint is True
    assert t_restored.requirements == deps
    assert t_restored(10) == 105


def test_serialization_bytes():
    """Test serializing to bytes and restoring from bytes."""

    deps = ["pandas"]

    @task(requirements=deps)
    def secret_math(x):
        # A test comment

        return x**2 + 5

    serialized_task = secret_math.to_bytes()

    assert isinstance(serialized_task, bytes)
    assert len(serialized_task) > 0

    t_restored = TaskSpec.from_bytes(serialized_task)

    assert isinstance(t_restored, TaskSpec)
    assert t_restored.name == "secret_math"
    assert t_restored.entrypoint is False
    assert t_restored.requirements == deps
    assert t_restored(10) == 105


def test_merge_requirements_preserves_explicit_specs():
    """Auto-discovered package names are appended without touching explicit specs."""
    merged = merge_requirements(
        ["numpy>=2.0", "pandas[extra]>=1.0"],
        {"numpy", "requests", "PANDAS"},
    )

    assert merged == ["numpy>=2.0", "pandas[extra]>=1.0", "requests"]

    # Empty discovered leaves explicit untouched
    assert merge_requirements(["numpy"], set()) == ["numpy"]
    # Empty explicit picks up all discovered (sorted)
    assert merge_requirements([], {"b", "a"}) == ["a", "b"]


def test_map_imports_to_packages():
    """
    Import names must map to their real pip package names before being
    auto-added to piprequirements (cv2 -> opencv-python, PIL -> pillow, ...).
    """
    # cv2 resolves to an OpenCV distribution whether it is installed locally
    # (authoritative importlib.metadata) or only known through the alias table.
    mapped_cv2 = map_imports_to_packages({"cv2"})
    assert any(pkg.startswith("opencv") for pkg in mapped_cv2), mapped_cv2

    # Alias tables apply when the package is not installed in the environment.
    for module, package in [
        ("skimage", "scikit-image"),
        ("bs4", "beautifulsoup4"),
        ("dotenv", "python-dotenv"),
        ("googleapiclient", "google-api-python-client"),
    ]:
        mapped = map_imports_to_packages({module})
        assert package in mapped, (module, mapped)

    # Names whose module name already matches their package are kept.
    assert map_imports_to_packages({"numpy"}) == {"numpy"}

    # Unknown names warn and are kept as-is (best-effort).
    assert map_imports_to_packages({"qall_test_unmappable_xyz"}) == {
        "qall_test_unmappable_xyz"
    }

    # Empty input yields no packages.
    assert map_imports_to_packages(set()) == set()


def test_discover_file_global_imports():
    """
    Only *global* (module body scope) third-party imports of the workflow file
    itself are discovered for auto-added piprequirements. Task-scope imports,
    sibling local modules, the stdlib and qall itself are excluded.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        (project_dir / "local_helper.py").write_text("def helper(): return 1\n")

        filepath = project_dir / "global_imports_main.py"
        filepath.write_text(textwrap.dedent("""
                import cv2
                import numpy as np
                from qall import task, workflow
                from pathlib import Path
                from local_helper import helper
                import itertools
                try:
                    from dateutil import parser  # noqa: F401
                except ImportError:
                    pass

                def non_task_func():
                    import task_scope_only_missing  # noqa: F401
                    return 1

                @task(piprequirements=["opencv-python"])
                def a():
                    import cv2
                    return helper(1)
                """))

        found = discover_file_global_imports(filepath)
        assert found == {"cv2", "numpy", "dateutil"}

        # Stdlib, qall, sibling local modules and task-scope imports excluded.
        assert "pathlib" not in found
        assert "itertools" not in found
        assert "qall" not in found
        assert "local_helper" not in found
        assert "task_scope_only_missing" not in found

    # A missing/unreadable file yields an empty set rather than raising.
    assert discover_file_global_imports("/nonexistent/workflow.py") == set()


def test_execution_with_scope_dependencies():

    var_dep = "hello night city"

    @task()
    def task_dep() -> str:
        return "!"

    def func_dep(s: str) -> str:
        return s + task_dep()

    @workflow()
    def my_wf():
        a = func_dep(var_dep)
        return a

    assert my_wf() == "hello night city!"

    ser = my_wf.to_bytes()
    wf_restored = TaskSpec.from_bytes(ser)
    assert wf_restored() == "hello night city!"

    ser = my_wf.to_json()
    wf_restored = TaskSpec.from_json(ser)
    assert wf_restored() == "hello night city!"


def test_extract_imports_from_function():
    """
    Tests that the AST parsing successfully identifies actively used imports,
    and correctly splits them into 'external_imports' (stdlib/third-party)
    and 'local_imports' (project files).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)

        # Create a local sibling module to test local import detection
        local_helper = base_dir / "my_local_helper.py"
        local_helper.write_text(textwrap.dedent("""
                def do_something_local():
                    return "local action"
                """))

        # Create an empty unused local module so Python doesn't crash on load
        missing_module = base_dir / "missing_module.py"
        missing_module.write_text(textwrap.dedent("""
                def dummy_func():
                    return 42
                """))

        # Create the main file with a mix of external, local, and unused imports
        main_file = base_dir / "test_imports.py"
        main_file.write_text(textwrap.dedent("""
                import math
                import os
                import sys as system
                from datetime import datetime, timedelta

                # Local imports
                import my_local_helper
                from missing_module import dummy_func  # Unused local

                def my_task_func():
                    # External usage
                    x = math.pi
                    v = system.version
                    now = datetime.now()
                    
                    # Local usage
                    res = my_local_helper.do_something_local()
                    
                    return x
                """))

        # Temporarily inject the temp dir into sys.path so the local import resolves safely
        sys.path.insert(0, str(base_dir))

        try:
            # Dynamically load the main file
            spec = importlib.util.spec_from_file_location(
                "test_imports_mod", str(main_file)
            )
            test_module = importlib.util.module_from_spec(spec)
            sys.modules["test_imports_mod"] = test_module
            spec.loader.exec_module(test_module)

            # Execute
            target_func = test_module.my_task_func
            extracted_imports = _extract_imports_from_function(target_func)

            # Dictionary structure check
            assert "external_imports" in extracted_imports
            assert "local_imports" in extracted_imports

            ext_imports = extracted_imports["external_imports"]
            loc_imports = extracted_imports["local_imports"]

            # External Imports Checks (3 used, 1 unused)
            assert len(ext_imports) == 3
            assert "import math" in ext_imports
            assert "import sys as system" in ext_imports
            assert "from datetime import datetime, timedelta" in ext_imports
            assert "import os" not in ext_imports

            # Local Imports Checks (1 used, 1 unused)
            assert len(loc_imports) == 1
            assert "import my_local_helper" in loc_imports
            assert "import missing_module" not in loc_imports

        finally:
            # Cleanup global state
            if str(base_dir) in sys.path:
                sys.path.remove(str(base_dir))
            if "test_imports_mod" in sys.modules:
                del sys.modules["test_imports_mod"]


### HARDENING UNIT TESTS ###


def _load_source_module(name: str, source: str, base_dir: Path) -> object:
    """Write `source` into a physical file and load it as `name`."""
    filepath = base_dir / f"{name}.py"
    filepath.write_text(textwrap.dedent(source))
    spec = importlib.util.spec_from_file_location(name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_extract_imports_aliased_task_decorator_not_captured():
    """The task library itself (even aliased/qualified) is never transported."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "alias_import_mod",
                """
                from qall import task as qtask

                @qtask()
                def f():
                    return 1
                """,
                Path(tmpdir),
            )
            extracted = _extract_imports_from_function(mod.f.func)
            assert extracted["external_imports"] == []
            assert extracted["local_imports"] == []
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("alias_import_mod", None)


def test_extract_imports_tl_module_import_filtered():
    """`import qall.specification` (qualified tl module) must be filtered too."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "tl_module_mod",
                """
                import math
                import qall.specification

                def f():
                    return math.pi + qall.specification.TaskSpec._mode.__len__()
                """,
                Path(tmpdir),
            )
            extracted = _extract_imports_from_function(mod.f)
            assert "import math" in extracted["external_imports"]
            assert not any("qall" in imp for imp in extracted["external_imports"])
            assert extracted["local_imports"] == []
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("tl_module_mod", None)


def test_extract_imports_function_body_imports_surfaced():
    """Imports made inside the function body are recorded as external imports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "body_import_mod",
                """
                import math

                def f():
                    from pprint import pprint as pp
                    pp("hi")
                    return math.pi
                """,
                Path(tmpdir),
            )
            extracted = _extract_imports_from_function(mod.f)
            assert "import math" in extracted["external_imports"]
            assert any("pprint" in imp for imp in extracted["external_imports"])
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("body_import_mod", None)


def test_extract_imports_function_prototype_annotations_captured():
    """Imports used only in a task's prototype (annotations) are captured."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "prototype_import_mod",
                """
                import datetime
                from pathlib import Path

                def f(path: Path, moment: datetime.datetime) -> Path:
                    return path
                """,
                Path(tmpdir),
            )
            extracted = _extract_imports_from_function(mod.f)
            assert "from pathlib import Path" in extracted["external_imports"]
            assert "import datetime" in extracted["external_imports"]
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("prototype_import_mod", None)


def test_json_roundtrip_prototype_annotation_type():
    """A task whose prototype uses a type survives JSON with it available."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "rt_prototype_mod",
                """
                from pathlib import Path

                def f(path: Path):
                    return str(path)
                """,
                Path(tmpdir),
            )
            spec = TaskSpec(func=mod.f)
            assert "from pathlib import Path" in spec.imports["external_imports"]
            restored = TaskSpec.from_json(spec.to_json())
            # The annotation-only import must be re-imported at reconstruction.
            assert "Path" in restored.func.__globals__
            assert restored(Path("/x")) == "/x"
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("rt_prototype_mod", None)


def test_bundle_local_dependencies_globals():
    """Path, datetime, containers of objects, lambdas and partials are bundled."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "bundle_globals_mod",
                """
                from pathlib import Path
                from datetime import datetime
                from functools import partial

                BASE_DIR = Path("/tmp/xyz")
                CREATED = datetime(2024, 1, 1)
                CONFIG = {"path": Path("/a"), "tags": {"x", "y"}}
                square = lambda v: v * v
                double = partial(int, base=2)
                FACTOR = 3

                def agg():
                    return {
                        "base": str(BASE_DIR),
                        "created": CREATED.isoformat(),
                        "square": square(FACTOR),
                        "double": double("1010"),
                        "tags": sorted(CONFIG["tags"]),
                    }
                """,
                Path(tmpdir),
            )
            deps = _bundle_local_dependencies(mod.agg)
            for key in ["BASE_DIR", "CREATED", "CONFIG", "square", "double", "FACTOR"]:
                assert key in deps, f"{key} should be bundled, got {sorted(deps)}"
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("bundle_globals_mod", None)


def test_bundle_local_dependencies_class_with_methods():
    """Classes are bundled along with the functions they reference from methods."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "bundle_class_mod",
                """
                class Helper:
                    CONST = 10

                    def method(self, x):
                        return x + Helper.CONST

                def inner(y):
                    return y * 2

                def use_helper():
                    h = Helper()
                    return h.method(inner(5))
                """,
                Path(tmpdir),
            )
            deps = _bundle_local_dependencies(mod.use_helper)
            assert "Helper" in deps
            assert "inner" in deps
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("bundle_class_mod", None)


def test_bundle_local_dependencies_excludes_taskspec():
    """Sub-task references are never bundled: they resolve via the task registry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "bundle_task_excl_mod",
                """
                from qall import task

                @task()
                def sub():
                    return 42

                def caller():
                    return sub()
                """,
                Path(tmpdir),
            )
            deps = _bundle_local_dependencies(mod.caller)
            assert "sub" not in deps
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("bundle_task_excl_mod", None)


def test_bundle_local_dependencies_excludes_qall_sdk_decorator():
    """
    The qall SDK's own decorator source must never be bundled into a task.

    Regression: `@qall.workflow()` / `@qall.task()` decorators were picked up
    by the module-member scan and their bare source (signature requires
    `Optional` from `typing`, which is never shipped) was injected into the
    entrypoint payload, crashing the runtime with
    `NameError: name 'Optional' is not defined`.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "bundle_sdk_decorator_mod",
                """
                import qall

                @qall.task()
                def prepare(x):
                    return x

                @qall.workflow()
                def main():
                    return prepare(5)
                """,
                Path(tmpdir),
            )
            main_deps = mod.main.local_dependencies
            assert "qall.workflow" not in main_deps
            assert "workflow" not in main_deps
            assert "qall.task" not in main_deps
            assert "task" not in main_deps
            assert not any(
                "def workflow" in source or "def task" in source
                for source in main_deps.values()
            )
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("bundle_sdk_decorator_mod", None)


def test_bundle_local_dependencies_excludes_qall_run_from_body():
    """
    SDK callables referenced from a task body (e.g. `qall.run`) are never
    bundled: they are available in the target runtime and their bare source
    would be broken (missing imports).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "bundle_sdk_run_mod",
                """
                import qall

                def f(qc):
                    return qall.run(qc, shots=10)
                """,
                Path(tmpdir),
            )
            deps = _bundle_local_dependencies(mod.f)
            assert "qall.run" not in deps
            assert "run" not in deps
            assert "create_quantum_run" not in deps
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("bundle_sdk_run_mod", None)


def test_bundle_module_members_user_local_module_still_bundled():
    """
    Positive control: members of *user* local modules accessed as `module.attr`
    (e.g. `utils.helper()`) must still be transported; only the qall task
    library itself is excluded.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            (Path(tmpdir) / "utils.py").write_text("def helper():\n    return 7\n")
            mod = _load_source_module(
                "bundle_local_member_mod",
                """
                import utils

                def f():
                    return utils.helper()
                """,
                Path(tmpdir),
            )
            deps = _bundle_local_dependencies(mod.f)
            assert "utils.helper" in deps
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("bundle_local_member_mod", None)
            # The sibling `utils` module was imported into sys.modules; drop it
            # so its (now deleted) temp file cannot leak into later tests.
            sys.modules.pop("utils", None)


def test_json_roundtrip_globals_with_path_and_objects():
    """A task relying on Path/datetime/lambda/partial globals survives JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "rt_globals_mod",
                """
                from pathlib import Path
                from datetime import datetime
                from functools import partial

                BASE_DIR = Path("/data")
                STARTED_AT = datetime(2025, 6, 1, 12, 0, 0)
                double = partial(lambda v: v * 2)

                def f():
                    return (str(BASE_DIR), STARTED_AT.isoformat(), double(21))
                """,
                Path(tmpdir),
            )
            spec = TaskSpec(func=mod.f)
            restored = TaskSpec.from_json(spec.to_json())
            assert restored() == mod.f()
            assert restored() == ("/data", "2025-06-01T12:00:00", 42)
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("rt_globals_mod", None)


def test_json_roundtrip_function_body_import():
    """Function-body imports survive reconstruction."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "rt_body_import_mod",
                """
                def f(x):
                    from math import pi
                    return round(x * pi, 2)
                """,
                Path(tmpdir),
            )
            spec = TaskSpec(func=mod.f)
            restored = TaskSpec.from_json(spec.to_json())
            assert restored(2) == mod.f(2) == round(2 * 3.141592653589793, 2)
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("rt_body_import_mod", None)


def test_json_roundtrip_local_module_attr_when_module_gone():
    """A local module accessed as module.attr is transported even if unimportable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        helper = Path(tmpdir) / "my_helper.py"
        helper.write_text("def helper_foo():\n    return 7\n")
        mod = _load_source_module(
            "rt_module_attr_mod",
            """
            import my_helper

            def f():
                return my_helper.helper_foo()
            """,
            Path(tmpdir),
        )
        spec = TaskSpec(func=mod.f)
        serialized = spec.to_json()

        # Simulate the target environment: the local module no longer exists.
        sys.path.remove(tmpdir)
        sys.modules.pop("my_helper", None)
        sys.modules.pop("rt_module_attr_mod", None)

        restored = TaskSpec.from_json(serialized)
        assert restored() == 7


def test_json_roundtrip_local_module_cloudpickle_value():
    """A local module member holding a non-literal value survives JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        helper = Path(tmpdir) / "val_lib.py"
        helper.write_text("from pathlib import Path\nP = Path('/data')\n")
        mod = _load_source_module(
            "rt_val_mod",
            """
            import val_lib

            def f():
                return str(val_lib.P)
            """,
            Path(tmpdir),
        )
        spec = TaskSpec(func=mod.f)
        serialized = spec.to_json()

        # Simulate the target environment: the local module no longer exists.
        sys.path.remove(tmpdir)
        sys.modules.pop("val_lib", None)
        sys.modules.pop("rt_val_mod", None)

        restored = TaskSpec.from_json(serialized)
        assert restored() == "/data"


def test_json_roundtrip_standalone_cross_task_reference():
    """A standalone task calling another task still resolves after JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sys.path.insert(0, tmpdir)
        try:
            mod = _load_source_module(
                "rt_cross_task_mod",
                """
                from qall import task

                @task()
                def inner(x):
                    return x + 1

                def wrapper(y):
                    return inner(y) * 2

                @task()
                def entry(z):
                    return wrapper(z)
                """,
                Path(tmpdir),
            )
            spec = mod.entry
            assert spec(10) == 22
            restored = TaskSpec.from_json(spec.to_json())
            assert restored(10) == 22
        finally:
            sys.path.remove(tmpdir)
            sys.modules.pop("rt_cross_task_mod", None)
