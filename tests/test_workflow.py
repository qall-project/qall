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

import asyncio
import importlib
from pathlib import Path
import sys
import textwrap
import pytest
import rustworkx as rx
import tempfile

from qall.specification import TaskSpec, WorkflowSpec

### HELPER ###


def _create_temp_module(source_code: str, module_name: str):
    """
    Helper function to dynamically create a physical Python file and load it as a module.
    This is strictly necessary because pyan3 and AST require a physical file path to parse,
    and using independent files ensures tasks from different tests do not pollute each other.
    """
    tmpdir = tempfile.mkdtemp()
    filepath = Path(tmpdir) / f"{module_name}.py"
    filepath.write_text(textwrap.dedent(source_code))

    spec = importlib.util.spec_from_file_location(module_name, str(filepath))
    test_module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = test_module
    spec.loader.exec_module(test_module)

    return test_module


### TESTS ###


def test_workflow_from_file():

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "test_workflow.py"
        filepath.write_text(textwrap.dedent("""
                from qall import task, workflow

                @workflow()
                def main():
                    return 42
                """))

        # Using a string
        my_wf = WorkflowSpec(str(filepath), "MyWorkflow")

        assert my_wf.name == "MyWorkflow"
        assert len(my_wf.tasks) == 1
        assert my_wf.tasks["main"] == my_wf.entrypoint_task
        assert isinstance(my_wf.graph, rx.PyDiGraph)
        assert len(my_wf.graph.nodes()) == 1
        assert my_wf.graph.nodes()[0] == my_wf.entrypoint_task.name
        assert len(my_wf.graph.edges()) == 0

        # Using a Path
        my_wf = WorkflowSpec(filepath, "MyWorkflow")

        assert my_wf.name == "MyWorkflow"
        assert len(my_wf.tasks) == 1
        assert my_wf.tasks["main"] == my_wf.entrypoint_task
        assert isinstance(my_wf.graph, rx.PyDiGraph)
        assert len(my_wf.graph.nodes()) == 1
        assert my_wf.graph.nodes()[0] == my_wf.entrypoint_task.name
        assert len(my_wf.graph.edges()) == 0


def test_workflow_from_file_with_missing_third_party_imports():
    """
    Building a WorkflowSpec must not require third-party packages to be
    installed locally: missing imports are stubbed during compilation, captured
    in imports['external_imports'] and auto-added to requirements.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # A local sibling that itself depends on a missing third-party package.
        (project_dir / "utils_helper.py").write_text(textwrap.dedent("""
            import qall_test_missing_requests

            def helper(x):
                return x + 1
            """))

        filepath = project_dir / "main_workflow.py"
        filepath.write_text(textwrap.dedent("""
            from qall import task, workflow
            import qall_test_missing_numpy as np
            from utils_helper import helper

            @workflow(requirements=["qall_test_missing_requests>=2.0"])
            def main():
                data = np.zeros((2, 2))
                return helper(1)
            """))

        my_wf = WorkflowSpec(filepath, "MyWorkflow")

        assert my_wf.name == "MyWorkflow"
        entry = my_wf.entrypoint_task
        assert entry is not None

        # Explicit spec preserved verbatim, discovered package auto-added once.
        # Sibling-file dependencies (utils_helper -> qall_test_missing_requests)
        # are NOT auto-added: only the workflow file's own global imports are.
        assert sorted(entry.requirements) == sorted(
            ["qall_test_missing_requests>=2.0", "qall_test_missing_numpy"]
        )
        assert entry.requirements.count("qall_test_missing_requests>=2.0") == 1
        assert entry.requirements.count("qall_test_missing_numpy") == 1
        # Missing third-party import captured for the task's own code.
        assert (
            "import qall_test_missing_numpy as np" in entry.imports["external_imports"]
        )

        # Stub modules must not leak into the process.
        assert "qall_test_missing_numpy" not in sys.modules
        assert "qall_test_missing_requests" not in sys.modules

        # JSON round-trip also works without the packages installed.
        loaded = WorkflowSpec.from_json(my_wf.to_json())
        assert loaded.entrypoint_task is not None
        assert loaded.name == "MyWorkflow"


def test_workflow_auto_requirements_use_package_names():
    """
    Auto-added root-scope dependencies must carry real pip package names, never
    raw import names: `import cv2` is auto-added as opencv-python and does not
    pollute per-task requirements (mirror of examples/7_remote_s3/main.py).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        filepath = project_dir / "main_s3.py"
        filepath.write_text(textwrap.dedent("""
                import cv2
                import numpy as np

                from qall import task, workflow

                @task(requirements=["opencv-python"])
                def download_images():
                    return cv2.imread("bucket/in.jpg")

                @task(requirements=["opencv-python"])
                def process_images(images):
                    return cv2.cvtColor(images, cv2.COLOR_BGR2GRAY)

                @workflow(requirements=["opencv-python"])
                def main():
                    return process_images(download_images())
                """))

        wf = WorkflowSpec(filepath, "S3Workflow")

        for task in wf.tasks.values():
            reqs = set(task.requirements)
            name = task.name
            # The bogus import name must never be auto-added as a package.
            assert "cv2" not in reqs, (name, reqs)
            # cv2 resolves to an OpenCV distribution.
            assert any(pkg.startswith("opencv") for pkg in reqs), (name, reqs)
            # Root-scope numpy is auto-added to every task (+ the entrypoint).
            assert "numpy" in reqs, (name, reqs)


def test_workflow_does_not_auto_add_task_scope_imports():
    """
    Imports made inside a task body (task-scope) are not auto-added to
    requirements: they remain the user's per-task manual responsibility.
    Only the file's *global* imports become root-scope pip packages.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        filepath = project_dir / "main_scoped.py"
        filepath.write_text(textwrap.dedent("""
                import numpy as np

                from qall import task, workflow

                @task()
                def a():
                    import qall_test_task_scoped_only  # noqa: F401
                    return np.zeros(1)

                @workflow()
                def main():
                    return a()
                """))

        wf = WorkflowSpec(filepath, "ScopedWorkflow")

        for task in wf.tasks.values():
            assert "qall_test_task_scoped_only" not in task.requirements, (
                task.name,
                task.requirements,
            )
            assert "numpy" in task.requirements, (task.name, task.requirements)


def test_workflow_prototype_third_party_type_captured():
    """
    A task whose prototype references a third-party type (the import is used
    only in annotations) must still capture that import so the worker runtime
    can re-import it and ship the package.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        filepath = project_dir / "main_workflow.py"
        filepath.write_text(textwrap.dedent("""
            from qall import task, workflow
            import qall_test_missing_numpy as np
            from pathlib import Path

            @task()
            def a(path: Path, arr: np.ndarray):
                return (str(path), arr.shape)

            @workflow()
            def main():
                return a(Path("/x"), np.zeros((2, 2)))
            """))

        my_wf = WorkflowSpec(filepath, "PrototypeWorkflow")
        task_a = my_wf.tasks["a"]

        # Prototype-only imports are captured (not just body imports).
        assert (
            "import qall_test_missing_numpy as np"
            in task_a.imports["external_imports"]
        )
        assert "from pathlib import Path" in task_a.imports["external_imports"]
        # The third-party package is auto-added to requirements.
        assert task_a.requirements.count("qall_test_missing_numpy") == 1

        # The captured imports are re-imported on reconstruction (stubbed here
        # since the package is not installed; resolved for real in the runtime
        # container where requirements are installed).
        restored = TaskSpec.from_json(task_a.to_json())
        assert "np" in restored.func.__globals__
        assert "Path" in restored.func.__globals__


def test_workflow_from_module():
    mod = _create_temp_module(
        """
        from qall import task, workflow

        @workflow()
        def main():
            return 42
        """,
        "wf_module_test",
    )

    # Initialize from ModuleType
    my_wf = WorkflowSpec(mod)

    assert my_wf.name == "wf_module_test"
    assert len(my_wf.tasks) == 1
    assert my_wf.tasks["main"] == my_wf.entrypoint_task


def test_workflow_from_task():
    mod = _create_temp_module(
        """
        from qall import task

        @task(entrypoint=True)
        def entry_task():
            return 1
        """,
        "wf_task_test",
    )

    # Initialize directly from the task object
    my_wf = WorkflowSpec(mod.entry_task)

    assert my_wf.name == "entry_task"
    assert len(my_wf.tasks) == 1
    assert my_wf.entrypoint_task == mod.entry_task


def test_declare_task_duplicate_raises_error():
    mod = _create_temp_module(
        """
        from qall import task

        @task(entrypoint=True)
        def dummy_task():
            pass
        """,
        "duplicate_task_mod",
    )

    # Init from Task
    my_wf = WorkflowSpec(mod.dummy_task)

    # Attempt to declare another task with the same resolved name
    t2 = TaskSpec(func=lambda: None)
    t2.name = "dummy_task"

    with pytest.raises(ValueError, match="Task name collision"):
        my_wf.declare_task(t2)


def test_multi_tasks_workflow():
    """Test that an entrypoint task calling other tasks works correctly."""
    mod = _create_temp_module(
        """
        from qall import task

        @task(requirements=["requests"])
        def fetch_data():
            return "data"

        @task(entrypoint=False)
        def process_data(d):
            return d + "_processed"

        @task(entrypoint=True, requirements=["pandas", "numpy"])
        def main_pipeline():
            raw = fetch_data()
            processed = process_data(raw)
            return processed
        """,
        "multi_task_mod",
    )

    my_wf = WorkflowSpec(mod)

    # Test Registry Population and Decorator Arguments
    assert len(my_wf.tasks) == 3
    assert "fetch_data" in my_wf.tasks
    assert "process_data" in my_wf.tasks
    assert "main_pipeline" in my_wf.tasks

    assert my_wf.entrypoint_task.name == "main_pipeline"
    assert set(my_wf.entrypoint_task.requirements) == {"pandas", "numpy"}
    assert set(my_wf.tasks["fetch_data"].requirements) == {"requests"}

    # Test Call Graph Generation
    assert len(my_wf.graph.nodes()) == 3
    assert len(my_wf.graph.edges()) == 2

    # Validate exact edge relationships
    edge_tuples = [
        (my_wf.graph[e[0]], my_wf.graph[e[1]]) for e in my_wf.graph.edge_list()
    ]
    assert ("main_pipeline", "fetch_data") in edge_tuples
    assert ("main_pipeline", "process_data") in edge_tuples


def test_entrypoint_task_setter():
    """Test setting the entrypoint task works and prevents overrides."""
    mod = _create_temp_module(
        """
        from qall import task

        @task(entrypoint=False)
        def dummy_logic():
            pass
        """,
        "setter_mod",
    )

    # Init from Module (no entrypoint naturally set)
    my_wf = WorkflowSpec(mod)

    t1 = TaskSpec(func=lambda: None)
    t1.name = "first_entrypoint"

    # Valid manual setting
    my_wf.entrypoint_task = t1
    assert my_wf.entrypoint_task == t1

    t2 = TaskSpec(func=lambda: None)
    t2.name = "second_entrypoint"

    # Invalid override
    with pytest.raises(ValueError, match="Entrypoint task already set"):
        my_wf.entrypoint_task = t2


def test_contains_logic():
    """Test the `in` keyword implementation (magic method __contains__)."""
    mod = _create_temp_module(
        """
        from qall import task
        
        @task(entrypoint=True)
        def t1(): 
            pass
        """,
        "contains_mod",
    )

    # Init from Task
    my_wf = WorkflowSpec(mod.t1)
    t1_task = my_wf.tasks["t1"]

    # String lookup
    assert "t1" in my_wf
    assert "non_existent_task" not in my_wf

    # Task instance lookup
    assert t1_task in my_wf

    # Unregistered ad-hoc task lookup
    unregistered_task = TaskSpec(func=lambda: None)
    assert unregistered_task not in my_wf

    # Type guard validation
    with pytest.raises(TypeError, match="Invalid type for membership test"):
        _ = 123 in my_wf


def test_bytes_serialization():
    """Test dumping and loading the Workflow to and from bytes (dumps, loads)."""
    mod = _create_temp_module(
        """
        from qall import task
        
        @task(entrypoint=True)
        def serial_task(): 
            pass
        """,
        "serialization_mod",
    )

    # Init from Module
    my_wf = WorkflowSpec(mod)

    # Serialize
    serialized_bytes = my_wf.dumps()
    assert isinstance(serialized_bytes, bytes)
    assert len(serialized_bytes) > 0

    # Deserialize
    loaded_wf = WorkflowSpec.loads(serialized_bytes)

    # Validate integrity
    assert loaded_wf.name == "serialization_mod"
    assert len(loaded_wf.tasks) == 1
    assert "serial_task" in loaded_wf.tasks
    assert loaded_wf.entrypoint_task.name == "serial_task"
    assert isinstance(loaded_wf.graph, rx.PyDiGraph)


def test_draw_no_graph(capsys):
    """Test draw safely exits if graph is None."""
    mod = _create_temp_module(
        """
        from qall import task
        
        @task(entrypoint=True)
        def draw_task(): 
            pass
        """,
        "draw_mod",
    )

    # Init from Task
    my_wf = WorkflowSpec(mod.draw_task)

    # Force the graph to None
    my_wf.graph = None

    my_wf.draw()

    # Capture stdout
    captured = capsys.readouterr()
    assert "Graph is not constructed yet. Build the workflow first." in captured.out


def test_workflow_deep_module_resolution_and_edge_collapsing():
    """
    Tests a twisted case where tasks call non-task intermediate functions
    across multiple nested files, which ultimately call other tasks.
    Verifies that the file discovery logic finds everything in sys.modules,
    and the edge collapsing logic bridges the distant tasks correctly.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        utils_dir = base_dir / "utils"
        utils_dir.mkdir()

        # Main workflow file
        wf_file = base_dir / "my_workflow.py"
        wf_file.write_text(textwrap.dedent("""
                import asyncio
                import random
                from qall import task, workflow
                from utils.utils_task import hw

                @task()
                def add(x, y):
                    return x + y

                @task(entrypoint=False)
                def mul(x, y):
                    tmp = 0
                    for i in range(x):
                        tmp = add(tmp, y)
                    return tmp

                # Intermediate non-task function
                def divide(x, y):
                    return mul(x, 1 / y)

                @workflow()
                async def main():
                    a = await hw()
                    b = add(a, 3)
                    n = random.randint(1, 10)
                    for i in range(n):
                        c = divide(b, 2)
                    return c
                """))

        # Sibling package files
        (utils_dir / "__init__.py").touch()

        (utils_dir / "utils_task.py").write_text(textwrap.dedent("""
                from qall import task
                from .blob import blob

                @task()
                async def hw():
                    return 42 + blob()
                """))

        (utils_dir / "blob.py").write_text(textwrap.dedent("""
                from .blob2 import yet_another_task

                # Intermediate non-task function
                def blob():
                    return yet_another_task() * 2
                """))

        (utils_dir / "blob2.py").write_text(textwrap.dedent("""
                from qall import task

                @task()
                def yet_another_task():
                    return "another damn task" * 2
                """))

        # Execute
        my_wf = WorkflowSpec(wf_file, "TwistedWorkflow")

        # Check Registry Integrity
        # Expected tasks: main, add, mul, hw, yet_another_task (5 total)
        # Note: 'divide' and 'blob' should NOT be here.
        assert len(my_wf.tasks) == 5
        assert "main" in my_wf.tasks
        assert "add" in my_wf.tasks
        assert "mul" in my_wf.tasks
        assert "hw" in my_wf.tasks
        assert "yet_another_task" in my_wf.tasks

        # Check Graph Nodes
        assert len(my_wf.graph.nodes()) == 5

        # Check Edges and Collapsing Logic
        edge_tuples = [
            (my_wf.graph[e[0]], my_wf.graph[e[1]]) for e in my_wf.graph.edge_list()
        ]

        # Did it bypass `blob()` to connect `hw` directly to `yet_another_task`?
        assert ("hw", "yet_another_task") in edge_tuples

        # Did it bypass `divide()` to connect `main` directly to `mul`?
        assert ("main", "mul") in edge_tuples

        # Standard direct task-to-task calls
        assert ("main", "hw") in edge_tuples
        assert ("main", "add") in edge_tuples
        assert ("mul", "add") in edge_tuples

        # Ensure no extra phantom edges were created
        assert len(edge_tuples) == 5


def test_workflow_call_and_orchestration_delegation():
    """
    Tests the Workflow.__call__() method and the 'remote execution'
    orchestration logic. Ensures that tasks calling normal functions,
    which in turn call other tasks, are properly routed through the
    task registry even after full serialization/deserialization.
    """
    mod = _create_temp_module(
        """
        from qall import task, workflow

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
        """,
        "workflow_call_mod",
    )

    # Initialize from Module
    # 'my_wf' inside the module is actually a Task object (with added entrypoint=True)
    orchestrated_wf = WorkflowSpec(mod.my_wf, "CallTestWorkflow")

    # Test the active local execution first
    assert (
        orchestrated_wf() == "hello night city!"
    ), "Local orchestrated execution failed"

    # Serialize to simulate sending to a remote worker
    serialized_bytes = orchestrated_wf.dumps()

    # Deserialize (Simulating the remote worker environment)
    # The remote worker rebuilds the workflow, recreating the registry
    restored_wf = WorkflowSpec.loads(serialized_bytes)

    # Remote Execution
    result = restored_wf()

    assert result == "hello night city!", "Deserialized orchestrated execution failed"


def test_workflow_json_serialization_and_execution():
    """
    Tests the JSON serialization and deserialization of a Workflow,
    including the rustworkx graph integrity, and ensures the remote
    execution logic (__call__) still works after JSON rehydration.
    """
    mod = _create_temp_module(
        """
        from qall import task, workflow

        base_val = 10

        @task(requirements=["math"])
        def multiply_task(x: int) -> int:
            return x * 2

        def helper_func(val: int) -> int:
            # Calls a subtask
            return multiply_task(val) + 5

        @workflow()
        def my_json_wf():
            # Calls a standard function, which calls a subtask
            res = helper_func(base_val)
            return res
        """,
        "json_workflow_mod",
    )

    # Initialize from the workflow task
    orchestrated_wf = WorkflowSpec(mod.my_json_wf, "JSONTestWorkflow")

    # Verify baseline execution (10 * 2 + 5 = 25)
    assert orchestrated_wf() == 25, "Local orchestrated execution failed"

    # Serialize to JSON
    json_payload = orchestrated_wf.to_json()

    assert isinstance(json_payload, str)
    assert "JSONTestWorkflow" in json_payload
    assert "my_json_wf" in json_payload
    assert "multiply_task" in json_payload

    # Deserialize from JSON (Simulating a remote environment)
    restored_wf = WorkflowSpec.from_json(json_payload)

    # Verify Structural Integrity
    assert restored_wf.name == "JSONTestWorkflow"
    assert len(restored_wf.tasks) == 2
    assert "my_json_wf" in restored_wf.tasks
    assert "multiply_task" in restored_wf.tasks

    # Verify DAG Integrity (Nodes should be strings now)
    assert restored_wf.graph is not None
    assert len(restored_wf.graph.nodes()) == 2
    assert len(restored_wf.graph.edges()) == 1

    # Reconstruct edge list based on the new string nodes
    edge_tuples = [
        (restored_wf.graph[source_idx], restored_wf.graph[target_idx])
        for source_idx, target_idx in restored_wf.graph.edge_list()
    ]
    assert ("my_json_wf", "multiply_task") in edge_tuples

    # Remote Execution Test
    result = restored_wf()

    assert result == 25, "Deserialized JSON orchestrated execution failed"


def test_workflow_to_and_from_file(tmp_path: Path):
    """
    Tests the to_file and from_file serialization methods, ensuring that
    both uncompressed JSON and LZMA compressed binaries are written,
    identified, and restored correctly.
    """
    mod = _create_temp_module(
        """
        from qall import task, workflow

        @task()
        def simple_task():
            return 42

        @workflow()
        def io_workflow():
            return simple_task()
        """,
        "file_io_mod",
    )

    # Initialize the workflow
    original_wf = WorkflowSpec(mod.io_workflow, "FileIOWorkflow")

    uncompressed_path = tmp_path / "uncompressed.json"
    compressed_path = tmp_path / "compressed.qall"

    # Test without compression
    original_wf.to_file(uncompressed_path, compression=False)

    assert uncompressed_path.exists()
    uncompressed_bytes = uncompressed_path.read_bytes()
    # Ensure it's not compressed (does not have LZMA magic bytes)
    assert not uncompressed_bytes.startswith(b"\xfd7zXZ\x00")

    restored_uncompressed = WorkflowSpec.from_file(uncompressed_path)
    assert restored_uncompressed.name == "FileIOWorkflow"
    assert "simple_task" in restored_uncompressed.tasks
    assert restored_uncompressed() == 42  # Verify execution state

    # Test with compression
    original_wf.to_file(compressed_path, compression=True)

    assert compressed_path.exists()
    compressed_bytes = compressed_path.read_bytes()
    # Verify the LZMA magic bytes signature is present
    assert compressed_bytes.startswith(b"\xfd7zXZ\x00")

    # from_file() should auto-detect the compression and decompress it seamlessly
    restored_compressed = WorkflowSpec.from_file(compressed_path)
    assert restored_compressed.name == "FileIOWorkflow"
    assert "simple_task" in restored_compressed.tasks
    assert restored_compressed() == 42  # Verify execution state

    missing_path = tmp_path / "ghost_file.json"
    with pytest.raises(
        FileNotFoundError, match="Cannot load Workflow. File not found:"
    ):
        WorkflowSpec.from_file(missing_path)


### HARDENING / GOLDEN / CORNER-CASE TESTS ###


def _write_file(base_dir: Path, relative: str, source: str) -> Path:
    """Write a nested source file, creating parent packages as needed."""
    path = base_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source))
    return path


def test_workflow_golden_basic_hierarchy():
    """
    Golden test mirroring examples/0_basic_hierarchy: nested modules, non-task
    intermediates, module-level imports, globals, async entrypoint and
    cross-file tasks. Verifies the 5-task DAG, exact edge set, local execution
    and both serialization round-trips.
    """
    example = (
        Path(__file__).resolve().parent.parent
        / "examples"
        / "0_basic_hierarchy"
        / "my_workflow.py"
    )
    assert example.exists(), f"Golden example missing: {example}"

    wf = WorkflowSpec(example, "Golden")

    # 5 tasks across 3 files
    assert sorted(wf.tasks) == ["add", "hw", "main", "mul", "yet_another_task"]
    assert wf.entrypoint_task.name == "main"

    edge_tuples = sorted((wf.graph[e[0]], wf.graph[e[1]]) for e in wf.graph.edge_list())
    assert edge_tuples == [
        ("hw", "yet_another_task"),  # through non-task blob()
        ("main", "add"),
        ("main", "hw"),
        ("main", "mul"),  # through non-task divide()
        ("mul", "add"),
    ]

    # Local execution: main -> divide(2, 45) = mul(2, 1/45) = 2/45
    assert wf() == 2 / 45

    # Bytes round-trip
    assert WorkflowSpec.loads(wf.dumps())() == 2 / 45

    # JSON round-trip
    assert WorkflowSpec.from_json(wf.to_json())() == 2 / 45


def test_workflow_edge_collapse_deep_chain_branch_shared():
    """
    Deep non-task chains (3+ hops), branching intermediates and a shared
    intermediate between two tasks must all collapse into direct task edges.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        wf_file = _write_file(
            base,
            "main.py",
            """
            from qall import task, workflow

            @task()
            def task_b(x):
                return x + 1

            def shared(x):
                return task_b(x)

            @task()
            def task_c(x):
                return shared(x) + 2

            def f3(x):
                return shared(x)

            def f2(x):
                return f3(x)

            def f1(x):
                return f2(x)

            @task()
            def task_a(x):
                return f1(x) + task_c(x)

            @workflow()
            def main():
                return task_a(1)
            """,
        )

        wf = WorkflowSpec(wf_file, "DeepChain")
        assert sorted(wf.tasks) == ["main", "task_a", "task_b", "task_c"]

        edge_tuples = sorted(
            (wf.graph[e[0]], wf.graph[e[1]]) for e in wf.graph.edge_list()
        )
        # main -> task_a (direct), task_a -> task_b (3 non-task hops),
        # task_a -> task_c (direct), task_c -> task_b (shared intermediate)
        assert edge_tuples == [
            ("main", "task_a"),
            ("task_a", "task_b"),
            ("task_a", "task_c"),
            ("task_c", "task_b"),
        ]

        assert wf() == 6
        assert WorkflowSpec.from_json(wf.to_json())() == 6


def test_workflow_edge_collapse_module_attr_path():
    """A task calling a local module member which itself calls a task."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        _write_file(
            base,
            "shared_tasks.py",
            """
            from qall import task

            @task()
            def compute(x):
                return x * 10
            """,
        )
        _write_file(
            base,
            "helpers.py",
            """
            from shared_tasks import compute

            def via_module(x):
                return compute(x)
            """,
        )
        _write_file(
            base,
            "runner_tasks.py",
            """
            from qall import task

            import helpers

            @task()
            def runner(x):
                return helpers.via_module(x)
            """,
        )
        wf_file = _write_file(
            base,
            "main.py",
            """
            from qall import task, workflow
            from runner_tasks import runner

            @workflow()
            def main():
                return runner(5)
            """,
        )

        wf = WorkflowSpec(wf_file, "ModuleAttr")
        assert sorted(wf.tasks) == ["compute", "main", "runner"]

        edge_tuples = sorted(
            (wf.graph[e[0]], wf.graph[e[1]]) for e in wf.graph.edge_list()
        )
        assert edge_tuples == [
            ("main", "runner"),
            ("runner", "compute"),
        ]

        assert wf() == 50
        assert WorkflowSpec.from_json(wf.to_json())() == 50


def test_workflow_cross_module_task_call():
    """A task imported from another module is callable and survives round-trip."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        _write_file(
            base,
            "pkg/__init__.py",
            "",
        )
        _write_file(
            base,
            "pkg/other.py",
            """
            from qall import task

            @task()
            def remote(x):
                return x * 2
            """,
        )
        wf_file = _write_file(
            base,
            "main.py",
            """
            from qall import task, workflow
            from pkg.other import remote

            @task()
            def local(x):
                return remote(x)

            @workflow()
            def main():
                return local(21)
            """,
        )

        wf = WorkflowSpec(wf_file, "CrossModule")
        assert sorted(wf.tasks) == ["local", "main", "remote"]

        edge_tuples = sorted(
            (wf.graph[e[0]], wf.graph[e[1]]) for e in wf.graph.edge_list()
        )
        assert edge_tuples == [("local", "remote"), ("main", "local")]

        assert wf() == 42
        assert WorkflowSpec.loads(wf.dumps())() == 42
        assert WorkflowSpec.from_json(wf.to_json())() == 42


def test_workflow_same_name_task_collision():
    """Two same-named tasks from different modules must raise a clear error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        _write_file(
            base,
            "mod_a.py",
            """
            from qall import task

            @task()
            def helper(x):
                return x + 1
            """,
        )
        _write_file(
            base,
            "mod_b.py",
            """
            from qall import task

            @task()
            def helper(x):
                return x * 2
            """,
        )
        wf_file = _write_file(
            base,
            "main.py",
            """
            from qall import task, workflow
            from mod_a import helper as helper_a
            from mod_b import helper as helper_b

            @workflow()
            def main():
                return helper_a(1) + helper_b(1)
            """,
        )

        with pytest.raises(ValueError, match="Task name collision"):
            WorkflowSpec(wf_file, "Collision")

        # The failure must not leak global state into later workflows.
        assert TaskSpec._parent_workflow is None
        assert TaskSpec._mode == "EXECUTION"


def test_workflow_async_inside_running_loop():
    """Running an async workflow from within an active event loop must work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mod = _create_temp_module(
            """
            import asyncio

            from qall import workflow

            @workflow()
            async def main():
                await asyncio.sleep(0)
                return 42
            """,
            "async_in_loop_mod",
        )
        wf = WorkflowSpec(mod, "AsyncLoop")

        async def call_from_loop():
            return wf()

        assert asyncio.run(call_from_loop()) == 42
        assert wf() == 42
        assert WorkflowSpec.from_json(wf.to_json())() == 42


def test_workflow_globals_path_and_custom_object():
    """Path and custom-object globals referenced by tasks survive round-trip."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mod = _create_temp_module(
            """
            from pathlib import Path

            from qall import task, workflow

            class Holder:
                def __init__(self, v):
                    self.v = v

            ROOT = Path("/opt/app")
            holder = Holder(10)

            @task()
            def use_globals():
                return (str(ROOT), holder.v)

            @workflow()
            def main():
                return use_globals()
            """,
            "globals_mod",
        )

        wf = WorkflowSpec(mod, "Globals")
        assert wf() == ("/opt/app", 10)
        assert WorkflowSpec.from_json(wf.to_json())() == ("/opt/app", 10)


def test_workflow_function_body_import_alias():
    """A task importing a stdlib alias inside its body works after round-trip."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mod = _create_temp_module(
            """
            from qall import task, workflow

            @task()
            def body_task(x):
                from collections import OrderedDict as od
                return od([("k", x)])

            @workflow()
            def main():
                d = body_task(5)
                return d["k"]
            """,
            "body_alias_mod",
        )

        wf = WorkflowSpec(mod, "BodyAlias")
        assert wf() == 5
        assert WorkflowSpec.from_json(wf.to_json())() == 5


def test_workflow_worst_case_convoluted():
    """
    Worst-case: deeply nested packages, cross-module tasks, async entrypoint and
    async non-task helpers, module.attr access to a local module, a class with
    methods, Path/datetime/lambda globals, function-body imports and long
    non-task call chains with branching -- all at once.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        _write_file(base, "utils/__init__.py", "")
        _write_file(
            base,
            "utils/constants.py",
            """
            from pathlib import Path
            from datetime import datetime

            BASE_DIR = Path("/data/root")
            STARTED_AT = datetime(2025, 6, 1, 12, 0, 0)
            OFFSET = 5
            double = lambda x: x * 2
            """,
        )
        _write_file(
            base,
            "utils/tasks.py",
            """
            from qall import task

            @task()
            def add(x, y):
                return x + y

            @task()
            def mul(x, y):
                from decimal import Decimal
                return int(Decimal(x) * Decimal(y))

            @task()
            def sub(x, y):
                return x - y

            @task()
            async def slow_add(x, y):
                return x + y
            """,
        )
        _write_file(
            base,
            "utils/helpers.py",
            """
            from utils.constants import OFFSET, double
            from utils.tasks import mul

            def apply_offset(x):
                return mul(x, OFFSET)

            def scaled(x):
                return double(x)

            def via_deep(x):
                y = apply_offset(x)
                return scaled(y)
            """,
        )
        _write_file(
            base,
            "utils/mathlib.py",
            """
            class Accumulator:
                def __init__(self, initial=0):
                    self.value = initial

                def bump(self, n):
                    self.value += n
                    return self.value
            """,
        )
        _write_file(base, "utils/data/__init__.py", "")
        _write_file(
            base,
            "utils/data/loader.py",
            """
            def load_config():
                return {"mode": "local"}
            """,
        )
        _write_file(base, "services/__init__.py", "")
        _write_file(
            base,
            "services/pipeline.py",
            """
            from qall import task

            @task()
            def run_pipeline(data):
                return f"pipeline({data})"
            """,
        )
        wf_file = _write_file(
            base,
            "my_workflow.py",
            """
            import asyncio
            from pathlib import Path

            from qall import task, workflow

            from utils.constants import BASE_DIR, STARTED_AT, OFFSET
            from utils.helpers import via_deep
            from utils.mathlib import Accumulator
            from utils.data import loader
            from services.pipeline import run_pipeline
            from utils.tasks import add, sub, slow_add

            async def something_async(x):
                return await slow_add(x, 100)

            def intermediate_a(x):
                return add(x, 1) - sub(x, 1)

            def intermediate_b(x):
                return via_deep(x)

            @task()
            def task_a(x):
                return intermediate_a(x)

            @task()
            def task_b(x):
                return intermediate_b(x)

            @workflow()
            async def main():
                acc = Accumulator(10)
                acc.bump(5)
                cfg = loader.load_config()
                base = Path(BASE_DIR) / cfg["mode"]
                r1 = await something_async(via_deep(OFFSET))
                r2 = task_a(r1)
                r3 = task_b(r2)
                r4 = run_pipeline(r3)
                return (str(base), acc.value, r4, STARTED_AT.isoformat())
            """,
        )

        wf = WorkflowSpec(wf_file, "WorstCase")
        expected_tasks = {
            "add",
            "main",
            "mul",
            "run_pipeline",
            "slow_add",
            "sub",
            "task_a",
            "task_b",
        }
        assert set(wf.tasks) == expected_tasks

        edge_tuples = sorted(
            (wf.graph[e[0]], wf.graph[e[1]]) for e in wf.graph.edge_list()
        )
        assert edge_tuples == [
            ("main", "mul"),  # via something_async -> via_deep -> apply_offset
            ("main", "run_pipeline"),
            ("main", "slow_add"),
            ("main", "task_a"),
            ("main", "task_b"),
            ("task_a", "add"),  # via intermediate_a (branching)
            ("task_a", "sub"),
            ("task_b", "mul"),  # via intermediate_b -> via_deep -> apply_offset
        ]

        expected = ("/data/root/local", 15, "pipeline(20)", "2025-06-01T12:00:00")
        assert wf() == expected
        assert WorkflowSpec.loads(wf.dumps())() == expected
        assert WorkflowSpec.from_json(wf.to_json())() == expected
