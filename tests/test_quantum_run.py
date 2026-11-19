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

import pytest

from qall import task
from qall.interop.mapping import normalize_circuit_type
from qall.specification.quantum_analyzer import _SampleAnalyzer, extract_samples
from qall.specification.workflow import WorkflowSpec


def test_quantum_sample_analyzer_qiskit_direct():
    source = textwrap.dedent(
        """
        import qall
        from qiskit import QuantumCircuit

        def execute():
            qc = QuantumCircuit(2)
            res = qall.sample(qc, shots=100)
            return res
        """
    )
    runs = _SampleAnalyzer(source).analyze()

    assert runs == [{"input_format": normalize_circuit_type("qiskit")}]


def test_quantum_sample_analyzer_aliased_import_and_cirq():
    source = textwrap.dedent(
        """
        from qall import sample as qsample
        import cirq

        def execute():
            circuit = cirq.Circuit()
            res = qsample(circuit, shots=50)
            return res
        """
    )
    runs = _SampleAnalyzer(source).analyze()

    assert runs == [{"input_format": normalize_circuit_type("cirq")}]


def test_quantum_sample_analyzer_typed_parameter():
    source = textwrap.dedent(
        """
        import qall
        from qiskit import QuantumCircuit

        def execute(circuit_qc: QuantumCircuit):
            return qall.sample(circuit_qc, shots=10)
        """
    )
    runs = _SampleAnalyzer(source).analyze()

    assert runs == [{"input_format": normalize_circuit_type("qiskit")}]


@pytest.mark.parametrize(
    "bad_source",
    [
        """
        import qall

        def execute(circuit_unk):
            return qall.sample(circuit_unk, shots=10)
        """,
        """
        import qall
        from unknown_sdk import CustomCircuit

        def execute():
            return qall.sample(CustomCircuit(), shots=10)
        """,
        """
        import qall

        def execute():
            return qall.sample("workflow_ref:v1", shots=10)
        """,
    ],
)
def test_quantum_sample_analyzer_rejects_unknown_or_unsupported_type(bad_source: str):
    with pytest.raises(ValueError):
        _SampleAnalyzer(textwrap.dedent(bad_source)).analyze()


def test_extract_quantum_samples_from_local_dependencies():
    main_task_source = textwrap.dedent(
        """
        def my_task():
            return helper_quantum_executor()
        """
    )

    helper_source = textwrap.dedent(
        """
        import qall
        from qiskit import QuantumCircuit

        def helper_quantum_executor():
            qc = QuantumCircuit(3)
            return qall.sample(qc, shots=200)
        """
    )

    def dummy_func():
        pass

    local_dependencies = {"helper_quantum_executor": helper_source}
    imports = {"external_imports": ["from qiskit import QuantumCircuit", "import qall"]}

    runs = extract_samples(
        func=dummy_func,
        source=main_task_source,
        local_dependencies=local_dependencies,
        imports=imports,
    )

    assert runs == [{"input_format": normalize_circuit_type("qiskit")}]


def test_task_spec_extracts_quantum_runs_automatically():
    @task()
    def quantum_task():
        import qall
        from qiskit import QuantumCircuit

        qc = QuantumCircuit(1)
        return qall.sample(qc, shots=10)

    assert hasattr(quantum_task, "quantum_runs")
    assert quantum_task.quantum_runs == [
        {"input_format": normalize_circuit_type("qiskit")}
    ]


def test_multi_framework_quantum_runs_in_single_task():
    """
    Verifies that a task containing multiple qall.sample() calls with different frameworks
    (Qiskit and Cirq in the same function) correctly extracts all typologies.
    """

    @task(min_qubits=2, qpu_modality="gate_based", requirements=["qiskit", "cirq"])
    def do_quantum_stuff(x, y):
        import cirq
        import qall
        import qiskit

        qc_qiskit = qiskit.QuantumCircuit(x)
        qc_qiskit.h(0)
        for i in range(1, x):
            qc_qiskit.cx(0, i)
        qc_qiskit.measure_all()
        result_qiskit = qall.sample(qc_qiskit, shots=10)

        qubits = cirq.LineQubit.range(2)
        qc_cirq = cirq.Circuit(
            cirq.H(qubits[0]),
            cirq.CNOT(qubits[0], qubits[1]),
            cirq.measure(*qubits, key="m"),
        )
        result_cirq = qall.sample(qc_cirq, shots=10)

        return result_qiskit, result_cirq

    runs = do_quantum_stuff.quantum_runs
    assert len(runs) == 2, f"Expected 2 quantum_runs, got: {runs}"

    input_formats = [r["input_format"] for r in runs]
    assert normalize_circuit_type("qiskit") in input_formats
    assert normalize_circuit_type("cirq") in input_formats


def test_quantum_sample_analyzer_diverse_typologies():
    """
    Tests the AST analyzer on several supported qall.sample() call typologies:
    Qiskit, Cirq, and a CUDA-Q kernel.
    """
    source = textwrap.dedent(
        """
        import cirq
        import cudaq
        import qall
        import qiskit

        @cudaq.kernel
        def bell():
            q = cudaq.qvector(2)
            h(q[0])
            x.ctrl(q[0], q[1])
            mz(q)

        def multi_typology_task():
            # Qiskit
            q_circ = qiskit.QuantumCircuit(2)
            res1 = qall.sample(q_circ, shots=100)

            # Cirq
            c_circ = cirq.Circuit()
            res2 = qall.sample(c_circ, shots=50)

            # CUDA-Q
            res3 = qall.sample(bell, shots=25)

            return res1, res2, res3
        """
    )

    runs = _SampleAnalyzer(source).analyze()

    assert len(runs) == 3
    assert all("dynamic" not in r for r in runs)

    formats = {r["input_format"] for r in runs}
    assert formats == {
        normalize_circuit_type("qiskit"),
        normalize_circuit_type("cirq"),
        normalize_circuit_type("cudaq"),
    }


def test_workflow_cudaq_kernel_compilation(tmp_path):
    """
    Verifies that a module-level @cudaq.kernel passed to qall.sample() is
    inferred as 'cudaq' and bundled as source in local_dependencies.
    """
    wf_file = tmp_path / "cudaq_workflow.py"
    wf_file.write_text(
        textwrap.dedent(
            """
            import cudaq
            import qall

            @cudaq.kernel
            def bell():
                q = cudaq.qvector(2)
                h(q[0])
                x.ctrl(q[0], q[1])
                mz(q)

            @qall.workflow(requirements=["cudaq"])
            def main():
                result = qall.sample(bell, shots=100)
                return {str(k): int(v) for k, v in result.items()}
            """
        )
    )

    wf_spec = WorkflowSpec(wf_file, "CudaqWorkflow")
    entry = wf_spec.tasks["main"]

    assert entry.quantum_runs == [{"input_format": normalize_circuit_type("cudaq")}]
    assert "bell" in entry.local_dependencies
    assert "@cudaq.kernel" in entry.local_dependencies["bell"]


def test_workflow_hybrid_file_compilation_and_graph(tmp_path):
    """
    Verifies full WorkflowSpec compilation from the user script example.
    Ensures all 3 tasks are registered and multi-framework quantum_runs
    in 'do_quantum_stuff' are preserved after file parsing.
    """
    wf_file = tmp_path / "hybrid_workflow.py"
    wf_file.write_text(
        textwrap.dedent(
            """
            import qall
            import qiskit
            import cirq
            from qiskit.result import Result
            from cirq.study.result import ResultDict
            from random import randint

            @qall.task()
            def prepare(x):
                return randint(1, x)

            @qall.task(min_qubits=2, qpu_modality="gate_based", requirements=["qiskit", "cirq"])
            def do_quantum_stuff(x, y):
                qc_qiskit = qiskit.QuantumCircuit(x)
                qc_qiskit.h(0)

                for i in range(1, x):
                    qc_qiskit.cx(0, i)

                qc_qiskit.measure_all()
                result_qiskit = qall.sample(qc_qiskit, shots=10)

                qubits = cirq.LineQubit.range(2)
                qc_cirq = cirq.Circuit(
                    cirq.H(qubits[0]),
                    cirq.CNOT(qubits[0], qubits[1]),
                    cirq.measure(*qubits, key="m"),
                )
                result_cirq = qall.sample(qc_cirq, shots=10)

                return (type(result_qiskit) is Result, type(result_cirq) is ResultDict)

            @qall.workflow()
            def main():
                a = prepare(10)
                b = do_quantum_stuff(a, 2)
                return b
            """
        )
    )

    wf_spec = WorkflowSpec(wf_file, "HybridWorkflow")

    # 1. Graph and task validation
    assert len(wf_spec.tasks) == 3
    assert "prepare" in wf_spec.tasks
    assert "do_quantum_stuff" in wf_spec.tasks
    assert "main" in wf_spec.tasks

    # 2. Validation of quantum_runs capture inside the quantum task
    quantum_task = wf_spec.tasks["do_quantum_stuff"]
    runs = quantum_task.quantum_runs
    assert len(runs) == 2

    extracted_formats = {r["input_format"] for r in runs}
    assert extracted_formats == {
        normalize_circuit_type("qiskit"),
        normalize_circuit_type("cirq"),
    }

    # 3. Validation of JSON serialization / deserialization roundtrip
    restored_wf = WorkflowSpec.from_json(wf_spec.to_json())
    restored_quantum_task = restored_wf.tasks["do_quantum_stuff"]
    assert restored_quantum_task.quantum_runs == runs
