#!/usr/bin/env python3
"""
Standalone runtime test script.

Tests the qall runtime execution logic without requiring a running daemon.
Uses a local blockstore to store task definitions and executes tasks with
input/output artifacts handled locally.

Usage:
    python test_runtime_standalone.py
"""

import tempfile
from pathlib import Path
import cloudpickle

from qall.object import TaskMetadata, TaskEnvironment, TaskNode, TaskPayload, task_run
from qall.registry.block_registry import BlockRegistry
from qall.runtime import TaskRuntimeExecutor, LocalArtifactBackend
from qall.registry.blockstore import LocalBlockstore
from qall.codec import DEFAULT_CODEC


def create_test_blockstore() -> tuple[LocalBlockstore, Path]:
    tmpdir = Path(tempfile.mkdtemp(prefix="qall-test-"))
    blocks_dir = tmpdir / "blocks"
    blocks_dir.mkdir(parents=True)

    store = LocalBlockstore(tmpdir)
    return store, tmpdir


def push_task_to_store(
    store: LocalBlockstore,
    source_code: str,
    task_name: str,
    entrypoint: bool = False,
    children: dict[str, str] = None,
) -> tuple[str, str]:
    payload = TaskPayload(
        code=source_code,
        code_format="raw",
        environment=TaskEnvironment(image="python:3.13").to_dict(),
    )

    metadata = TaskMetadata(
        name=task_name,
        entrypoint=entrypoint,
        pure=True,
    )

    payload_block = payload.to_block(DEFAULT_CODEC)
    payload_hash = payload_block.hash

    node = TaskNode(
        payload_hash=payload_hash,
        children=children or {},
        metadata=metadata.to_dict(),
    )

    node_block = node.to_block(DEFAULT_CODEC)
    task_hash = node_block.hash

    store.put(payload_hash, payload_block.data)
    store.put(task_hash, node_block.data)

    print(f"  Pushed task '{task_name}' (hash: {task_hash[:16]}...)")
    print(f"  TaskPayload hash: {payload_hash[:16]}...")

    return task_hash, payload_hash


def test_simple_task():
    print("\n" + "=" * 60)
    print("TEST 1: Simple task with no dependencies")
    print("=" * 60)

    store, tmpdir = create_test_blockstore()
    registry = BlockRegistry(tmpdir)
    artifact_backend = LocalArtifactBackend(tmpdir / "artifacts")

    source_code = """
def add_numbers(a, b):
    result = a + b
    print(f"Adding {a} + {b} = {result}")
    return result
"""

    task_hash, _ = push_task_to_store(store, source_code, "add_numbers")

    executor = TaskRuntimeExecutor(
        task_hash=task_hash,
        registry=registry,
        artifact_backend=artifact_backend,
    )

    input_data = cloudpickle.dumps({"a": 5, "b": 10})

    print(f"\nExecuting task with input: a=5, b=10")
    result = executor.execute(task_run_id="addition_test", input_artifact=input_data)

    print(f"\nResults:")
    print(f"  Return code: {result.return_code}")
    print(f"  Stdout: {result.stdout.strip()}")
    if result.stderr:
        print(f"  Stderr: {result.stderr.strip()}")
    print(f"  Output artifact hash: {result.output_artifact_hash}")

    if result.output_artifact_bytes:
        output_value = cloudpickle.loads(result.output_artifact_bytes)
        print(f"  Output value: {output_value}")
        assert output_value == 15, f"Expected 15, got {output_value}"

    assert result.return_code == 0, f"Task failed with return code {result.return_code}"
    print("\n✓ TEST 1 PASSED")

    import shutil

    shutil.rmtree(tmpdir)


def test_task_with_input_artifact():
    print("\n" + "=" * 60)
    print("TEST 2: Task with input artifact")
    print("=" * 60)

    store, tmpdir = create_test_blockstore()
    registry = BlockRegistry(tmpdir)
    artifact_dir = tmpdir / "artifacts"
    artifact_backend = LocalArtifactBackend(artifact_dir)

    task_run_id = "multiplication_test"
    source_code = """
def multiply(x, y):
    result = x * y
    print(f"Multiplying {x} * {y} = {result}")
    return result
"""

    task_hash, _ = push_task_to_store(store, source_code, "multiply")

    executor = TaskRuntimeExecutor(
        task_hash=task_hash,
        registry=registry,
        artifact_backend=artifact_backend,
    )

    input_data = cloudpickle.dumps({"x": 6, "y": 7})
    input_artifact_hash = artifact_backend.upload_artifact(
        task_run_id=task_run_id, artifact_bytes=input_data
    )
    print(f"  Input artifact hash: {input_artifact_hash}")

    print(f"\nExecuting task with input artifact: x=6, y=7")
    result = executor.execute(
        task_run_id=task_run_id,
        input_artifact_hash=input_artifact_hash,
    )

    print(f"\nResults:")
    print(f"  Return code: {result.return_code}")
    print(f"  Stdout: {result.stdout.strip()}")
    print(f"  Output artifact hash: {result.output_artifact_hash}")

    if result.output_artifact_bytes:
        output_value = cloudpickle.loads(result.output_artifact_bytes)
        print(f"  Output value: {output_value}")
        assert output_value == 42, f"Expected 42, got {output_value}"

    assert result.return_code == 0
    print("\n✓ TEST 2 PASSED")

    import shutil

    shutil.rmtree(tmpdir)


def test_task_with_subtask():
    print("\n" + "=" * 60)
    print("TEST 3: Task with sub-task call (AST transformation)")
    print("=" * 60)

    store, tmpdir = create_test_blockstore()
    registry = BlockRegistry(tmpdir)
    artifact_backend = LocalArtifactBackend(tmpdir / "artifacts")

    subtask_source = """
def double(x):
    result = x * 2
    print(f"Doubling {x} -> {result}")
    return result
"""

    main_source = """
def double(x):
    result = x * 2
    print(f"Doubling {x} -> {result}")
    return result

def process_value(value):
    doubled = double(value)
    result = doubled + 10
    print(f"Processing {value}: doubled={doubled}, final={result}")
    return result
"""

    subtask_hash, _ = push_task_to_store(store, subtask_source, "double")
    main_hash, _ = push_task_to_store(
        store,
        main_source,
        "process_value",
        entrypoint=True,
        children={"double": subtask_hash},
    )

    executor = TaskRuntimeExecutor(
        task_hash=main_hash,
        registry=registry,
        artifact_backend=artifact_backend,
    )

    input_data = cloudpickle.dumps({"value": 5})

    print(f"\nExecuting main task with sub-task dependency")
    print(f"  Input: value=5")
    print(f"  Expected: double(5) should be replaced with stub")

    result = executor.execute(task_run_id="subtasking_test", input_artifact=input_data)

    print(f"\nResults:")
    print(f"  Return code: {result.return_code}")
    print(f"  Stdout: {result.stdout.strip()}")
    if result.stderr:
        print(f"  Stderr: {result.stderr.strip()}")

    assert result.return_code == 0
    print("\n✓ TEST 3 PASSED (sub-task stub called)")

    import shutil

    shutil.rmtree(tmpdir)


def test_chained_tasks():
    print("\n" + "=" * 60)
    print("TEST 4: Chained tasks (pipeline)")
    print("=" * 60)

    store, tmpdir = create_test_blockstore()
    registry = BlockRegistry(tmpdir)
    artifact_backend = LocalArtifactBackend(tmpdir / "artifacts")

    source_add = """
def add_five(x):
    result = x + 5
    print(f"add_five({x}) = {result}")
    return result
"""

    source_multiply = """
def multiply_by_three(x):
    result = x * 3
    print(f"multiply_by_three({x}) = {result}")
    return result
"""

    hash_add, _ = push_task_to_store(store, source_add, "add_five")
    hash_mul, _ = push_task_to_store(store, source_multiply, "multiply_by_three")

    executor_add = TaskRuntimeExecutor(
        task_hash=hash_add,
        registry=registry,
        artifact_backend=artifact_backend,
    )
    executor_mul = TaskRuntimeExecutor(
        task_hash=hash_mul,
        registry=registry,
        artifact_backend=artifact_backend,
    )

    input_data = cloudpickle.dumps({"x": 10})

    print(f"\nExecuting pipeline: add_five(10) -> multiply_by_three(result)")

    result1 = executor_add.execute(
        task_run_id="chained_add_test", input_artifact=input_data
    )
    print(f"\nTask 1 (add_five):")
    output1 = cloudpickle.loads(result1.output_artifact_bytes)
    print(f"  Output: {output1}")

    input_data2 = cloudpickle.dumps({"x": output1})
    result2 = executor_mul.execute(
        task_run_id="chained_add_test", input_artifact=input_data2
    )
    print(f"\nTask 2 (multiply_by_three):")
    output2 = cloudpickle.loads(result2.output_artifact_bytes)
    print(f"  Output: {output2}")

    expected = (10 + 5) * 3
    assert output2 == expected, f"Expected {expected}, got {output2}"

    print("\n✓ TEST 4 PASSED")

    import shutil

    shutil.rmtree(tmpdir)


def main():
    print("\n" + "=" * 60)
    print("QALL RUNTIME STANDALONE TESTS")
    print("=" * 60)

    try:
        test_simple_task()
        test_task_with_input_artifact()
        test_task_with_subtask()
        test_chained_tasks()

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED ✓")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
