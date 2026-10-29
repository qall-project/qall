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

from qall import task
from qall.specification.quantum_run import _QuantumRunAnalyzer, extract_quantum_runs
from qall.specification.workflow import WorkflowSpec
from qall.interop.mapping import normalize_circuit_type, normalize_result_type


def test_quantum_run_analyzer_qiskit_direct():
    source = textwrap.dedent("""
        import qall
        from qiskit import QuantumCircuit

        def execute():
            qc = QuantumCircuit(2)
            res = qall.run(qc, shots=100)
            return res
        """)
    analyzer = _QuantumRunAnalyzer(source)
    runs = analyzer.analyze()

    assert len(runs) == 1
    assert runs[0]["input_format"] == normalize_circuit_type("qiskit")
    assert runs[0]["dynamic"] is False


def test_quantum_run_analyzer_aliased_import_and_cirq():
    source = textwrap.dedent("""
        from qall import run as qrun
        import cirq

        def execute():
            circuit = cirq.Circuit()
            res = qrun(circuit, shots=50)
            return res
        """)
    analyzer = _QuantumRunAnalyzer(source)
    runs = analyzer.analyze()

    assert len(runs) == 1
    assert runs[0]["input_format"] == normalize_circuit_type("cirq")
    assert runs[0]["dynamic"] is False


def test_quantum_run_analyzer_dynamic_or_unknown_type():
    source = textwrap.dedent("""
        import qall

        def execute(circuit_unk):
            return qall.run(circuit_unk, shots=10)
        """)
    analyzer = _QuantumRunAnalyzer(source)
    runs = analyzer.analyze()

    assert len(runs) == 1
    assert runs[0]["input_format"] is None
    assert runs[0]["dynamic"] is True


def test_extract_quantum_runs_from_local_dependencies():
    main_task_source = textwrap.dedent("""
        def my_task():
            return helper_quantum_executor()
        """)

    helper_source = textwrap.dedent("""
        import qall
        from qiskit import QuantumCircuit

        def helper_quantum_executor():
            qc = QuantumCircuit(3)
            return qall.run(qc, shots=200)
        """)

    def dummy_func():
        pass

    local_dependencies = {"helper_quantum_executor": helper_source}
    imports = {"external_imports": ["from qiskit import QuantumCircuit", "import qall"]}

    runs = extract_quantum_runs(
        func=dummy_func,
        source=main_task_source,
        local_dependencies=local_dependencies,
        imports=imports,
    )

    assert len(runs) == 1
    assert runs[0]["input_format"] == normalize_circuit_type("qiskit")
    assert runs[0]["dynamic"] is False


def test_task_spec_extracts_quantum_runs_automatically():
    @task()
    def quantum_task():
        import qall
        from qiskit import QuantumCircuit

        qc = QuantumCircuit(1)
        return qall.run(qc, shots=10)

    assert hasattr(quantum_task, "quantum_runs")
    assert len(quantum_task.quantum_runs) == 1
    assert quantum_task.quantum_runs[0]["input_format"] == normalize_circuit_type(
        "qiskit"
    )


def test_multi_framework_quantum_runs_in_single_task():
    """
    Verifies that a task containing multiple qall.run() calls with different frameworks
    (Qiskit and Cirq in the same function) correctly extracts all typologies.
    """

    @task(min_qubits=2, qpu_modality="gate_based", requirements=["qiskit", "cirq"])
    def do_quantum_stuff(x, y):
        import qall
        import qiskit
        import cirq

        qc_qiskit = qiskit.QuantumCircuit(x)
        qc_qiskit.h(0)
        for i in range(1, x):
            qc_qiskit.cx(0, i)
        qc_qiskit.measure_all()
        result_qiskit = qall.run(qc_qiskit, shots=10)

        qubits = cirq.LineQubit.range(2)
        qc_cirq = cirq.Circuit(
            cirq.H(qubits[0]),
            cirq.CNOT(qubits[0], qubits[1]),
            cirq.measure(*qubits, key="m"),
        )
        result_cirq = qall.run(qc_cirq, shots=10)

        return result_qiskit, result_cirq

    # Static inspection of extracted quantum_runs in TaskSpec
    runs = do_quantum_stuff.quantum_runs
    assert len(runs) == 2, f"Expected 2 quantum_runs, got: {runs}"

    input_formats = [r["input_format"] for r in runs]
    assert normalize_circuit_type("qiskit") in input_formats
    assert normalize_circuit_type("cirq") in input_formats
    assert all(r["dynamic"] is False for r in runs)


def test_quantum_run_analyzer_diverse_typologies():
    """
    Tests the AST analyzer on several qall.run() call typologies:
    Qiskit, Cirq, and an opaque dynamic argument that cannot be typed statically.
    """
    source = textwrap.dedent("""
        import qall
        import qiskit
        import cirq

        def multi_typology_task(opaque_circuit):
            # Qiskit
            q_circ = qiskit.QuantumCircuit(2)
            res1 = qall.run(q_circ, shots=100)

            # Cirq
            c_circ = cirq.Circuit()
            res2 = qall.run(c_circ, shots=50)

            # Dynamic argument (circuit passed as a parameter)
            res3 = qall.run(opaque_circuit, shots=10)

            return res1, res2, res3
        """)

    analyzer = _QuantumRunAnalyzer(source)
    runs = analyzer.analyze()

    assert len(runs) == 3

    # Extracted formats
    formats = [r["input_format"] for r in runs]
    assert normalize_circuit_type("qiskit") in formats
    assert normalize_circuit_type("cirq") in formats
    assert None in formats  # Dynamic

    # Dynamic flag validation
    dynamic_map = {r["input_format"]: r["dynamic"] for r in runs}
    assert dynamic_map[normalize_circuit_type("qiskit")] is False
    assert dynamic_map[normalize_circuit_type("cirq")] is False
    assert dynamic_map[None] is True


def test_workflow_hybrid_file_compilation_and_graph(tmp_path):
    """
    Verifies full WorkflowSpec compilation from the user script example.
    Ensures all 3 tasks are registered and multi-framework quantum_runs
    in 'do_quantum_stuff' are preserved after file parsing.
    """
    wf_file = tmp_path / "hybrid_workflow.py"
    wf_file.write_text(textwrap.dedent("""
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
                result_qiskit = qall.run(qc_qiskit, shots=10)

                qubits = cirq.LineQubit.range(2)
                qc_cirq = cirq.Circuit(
                    cirq.H(qubits[0]),
                    cirq.CNOT(qubits[0], qubits[1]),
                    cirq.measure(*qubits, key="m"),
                )
                result_cirq = qall.run(qc_cirq, shots=10)

                return (type(result_qiskit) is Result, type(result_cirq) is ResultDict)

            @qall.workflow()
            def main():
                a = prepare(10)
                b = do_quantum_stuff(a, 2)
                return b
            """))

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
    assert len(restored_quantum_task.quantum_runs) == 2
