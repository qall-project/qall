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
import textwrap
from pathlib import Path
import pytest

from qall.specification import WorkerSpec
from qall.registry import BlockRegistry
from qall.object import WorkerNode, WorkerPayload, WorkerMetadata, Tag
from qall.runtime import WorkerRuntimeExecutor
from qall.provider.worker import QuantumWorker
from qall.interop.mapping import normalize_circuit_type, normalize_result_type


@pytest.fixture
def local_registry(tmp_path: Path):
    registry_path = tmp_path / "block_registry"
    return BlockRegistry(local_root_dir=registry_path)


def test_worker_spec_inlining_and_relative_import_stripping(tmp_path: Path):
    pkg_dir = tmp_path / "my_worker_pkg"
    pkg_dir.mkdir()

    utils_file = pkg_dir / "utils.py"
    utils_file.write_text(
        textwrap.dedent(
            """
            def format_shots(shots: int) -> int:
                return max(1, shots)

            def get_default_context_name() -> str:
                return "default_ctx"
            """
        )
    )

    worker_file = pkg_dir / "my_local_worker.py"
    worker_file.write_text(
        textwrap.dedent(
            """
            from .utils import format_shots, get_default_context_name
            from qall.provider.qc import (
                QuantumWorker,
                QuantumContext,
                quantum_worker,
            )

            @quantum_worker(
                input_format="qiskit",
                output_format="qiskit",
                provider="local_test",
            )
            class LocalTestWorker(QuantumWorker):
                def create_context(self, resource, context, **kwargs):
                    return context

                def run(self, program, shots, context, **kwargs):
                    clean_shots = format_shots(shots)
                    return program

                def close_context(self, context, **kwargs):
                    return context
            """
        )
    )

    spec = WorkerSpec(worker_file)

    assert spec.name == "LocalTestWorker"
    assert spec.input_format == normalize_circuit_type("qiskit")
    assert spec.output_format == normalize_result_type("qiskit")
    assert spec.provider == "local_test"

    assert "from .utils import" not in spec.source

    assert "def format_shots" in spec.source
    assert "def get_default_context_name" not in spec.source

    assert "format_shots" in spec.local_dependencies


def test_worker_push_and_pull_from_registry(
    tmp_path: Path, local_registry: BlockRegistry
):
    worker_file = tmp_path / "dummy_worker.py"
    worker_file.write_text(
        textwrap.dedent(
            """
            from qall.provider.qc import (
                QuantumWorker,
                QuantumContext,
                quantum_worker,
            )

            def local_helper(val):
                return val * 2

            @quantum_worker(
                input_format="cirq",
                output_format="cirq",
                provider="test_provider",
            )
            class DummyWorker(QuantumWorker):
                def create_context(self, resource, context, **kwargs):
                    return context

                def run(self, program, shots, context, **kwargs):
                    return local_helper(shots)

                def close_context(self, context, **kwargs):
                    return context
            """
        )
    )

    spec = WorkerSpec(worker_file)
    dag = local_registry.create_worker_dag(spec)

    tag = Tag(name="dummy_worker", version="latest")
    root_hash = local_registry.push(tag=tag, dag=dag)

    assert root_hash == tag.uri

    node: WorkerNode = local_registry.get_worker_node_from_local(dag.root_hash)
    assert node is not None
    assert node.metadata["name"] == "DummyWorker"
    assert node.metadata["input_format"] == normalize_circuit_type("cirq")
    assert node.metadata["output_format"] == normalize_result_type("cirq")
    assert node.metadata["provider"] == "test_provider"

    payload: WorkerPayload = local_registry.get_worker_payload_from_local(
        node.payload_hash
    )
    assert payload is not None
    assert payload.code_format == "qio.program"


def test_worker_reconstruction_and_loading(
    tmp_path: Path, local_registry: BlockRegistry
):
    worker_file = tmp_path / "executable_worker.py"
    worker_file.write_text(
        textwrap.dedent(
            """
            from qall.provider.qc import (
                QuantumWorker,
                QuantumContext,
                quantum_worker,
            )

            def compute_multiplier():
                return 10

            @quantum_worker(
                input_format="qiskit",
                output_format="qiskit",
                provider="exec_provider",
            )
            class ExecutableWorker(QuantumWorker):
                def create_context(self, resource, context, **kwargs):
                    return context

                def run(self, program, shots, context, **kwargs):
                    return shots * compute_multiplier()

                def close_context(self, context, **kwargs):
                    return context
            """
        )
    )

    spec = WorkerSpec(worker_file)
    dag = local_registry.create_worker_dag(spec)
    local_registry.push(dag=dag, tag=Tag(version="v1", name="dumwork"))

    executor = WorkerRuntimeExecutor(
        worker_hash=dag.root_hash,
        registry=local_registry,
        port=50099,
    )

    node = local_registry.get_worker_node_from_local(dag.root_hash)
    payload = local_registry.get_worker_payload_from_local(node.payload_hash)
    metadata = WorkerMetadata(**node.metadata)

    worker_instance = executor._load_worker(payload=payload, metadata=metadata)
    assert isinstance(worker_instance, QuantumWorker)
    assert worker_instance.capabilities.input_format == normalize_circuit_type("qiskit")
    assert worker_instance.capabilities.output_format == normalize_result_type("qiskit")
    assert worker_instance.run(None, 5, None) == 50
