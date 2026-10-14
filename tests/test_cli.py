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

import argparse
import json
import lzma
import pytest
import textwrap

from pathlib import Path


from qall.specification import WorkflowSpec


def workflow_create(args):
    print(f"Creating workflow from file: {args.file}")

    name = args.name
    if name is None:
        name = Path(args.file).stem

    wf = WorkflowSpec(Path(args.file), name)

    if args.output:
        wf.to_file(Path(args.output), compression=args.compression)

    if args.graph:
        wf.draw()

    return wf


def workflow_load(args):
    print(f"Loading a workflow from file: {args.file}...")

    wf = WorkflowSpec.from_file(Path(args.file))

    print(f"Loaded Workflow: {wf.name} with {len(wf.task_registry)} tasks!")

    if args.graph:
        wf.draw()

    return wf


def workflow_run(args):
    if args.workflow_name and not args.file:
        print(f"Running workflow named: {args.workflow_name}")
        raise NotImplementedError("Workflow execution not implemented yet.")
    elif args.file:
        wf = WorkflowSpec.from_file(Path(args.file))
        print(f"Running workflow from file: {args.file}")
        result = wf()

    print(f"Result: {result}")

    return result


# --- FIXTURES ---


@pytest.fixture
def dummy_workflow_file(tmp_path: Path) -> Path:
    """
    Generates a real, executable python file containing a Qall workflow
    to be used by the CLI handler tests.
    """
    filepath = tmp_path / "test_pipeline.py"
    filepath.write_text(
        textwrap.dedent("""
            from qall import task, workflow

            @task()
            def my_subtask():
                return 21

            @workflow()
            def my_main_wf():
                return my_subtask() * 2
            """),
        encoding="utf-8",
    )
    return filepath


@pytest.fixture
def dummy_json_workflow(dummy_workflow_file: Path, tmp_path: Path) -> Path:
    """
    Compiles the dummy workflow and serializes it to JSON for loading/running tests.
    """
    wf = WorkflowSpec(dummy_workflow_file, "TestJsonWF")
    json_path = tmp_path / "test_pipeline.json"
    json_path.write_text(wf.to_json(), encoding="utf-8")
    return json_path


# --- HANDLER TESTS ---


def test_handle_workflow_create_default_name(dummy_workflow_file: Path):
    """Test creating a workflow infers the name from the file if no name is provided."""
    args = argparse.Namespace(
        file=dummy_workflow_file,
        name=None,
        output=None,
        graph=False,
    )

    wf = workflow_create(args)

    assert isinstance(wf, WorkflowSpec)
    assert wf.name == "test_pipeline"
    assert "my_main_wf" in wf.tasks
    assert "my_subtask" in wf.tasks


def test_handle_workflow_create_with_output(dummy_workflow_file: Path, tmp_path: Path):
    """Test creating a workflow with explicit name and output serialization."""
    output_file = tmp_path / "out.json"

    args = argparse.Namespace(
        file=dummy_workflow_file,
        name="CustomDAG",
        output=str(output_file),
        graph=False,
        compression=True,
    )

    wf = workflow_create(args)

    assert isinstance(wf, WorkflowSpec)
    assert wf.name == "CustomDAG"

    assert output_file.exists()

    loaded_state = json.loads(lzma.decompress(output_file.read_bytes()).decode("utf-8"))
    assert loaded_state["name"] == "CustomDAG"
    assert "my_main_wf" in loaded_state["tasks"]


def test_handle_workflow_load(dummy_json_workflow: Path):
    """Test loading a workflow from a serialized JSON file."""
    args = argparse.Namespace(
        file=dummy_json_workflow,
        graph=False,
    )

    wf = workflow_load(args)

    assert isinstance(wf, WorkflowSpec)
    assert wf.name == "TestJsonWF"
    assert len(wf.tasks) == 2
    assert wf.entrypoint_task.name == "my_main_wf"


def test_handle_workflow_run_not_implemented():
    """Test that running a workflow by name only raises NotImplementedError."""
    args = argparse.Namespace(
        workflow_name="my_workflow",
        file=None,
    )

    with pytest.raises(
        NotImplementedError, match="Workflow execution not implemented yet"
    ):
        workflow_run(args)


def test_handle_workflow_run_from_file(dummy_json_workflow: Path):
    """Test that running a workflow from a JSON file actually executes it."""
    args = argparse.Namespace(
        workflow_name=None,
        file=dummy_json_workflow,
    )

    result = workflow_run(args)

    assert result == 42
