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
from qall.interop.mapping import normalize_circuit_type, normalize_result_type


def test_quantum_run_analyzer_qiskit_direct():
    source = textwrap.dedent(
        """
        import qall
        from qiskit import QuantumCircuit

        def execute():
            qc = QuantumCircuit(2)
            res = qall.run(qc, shots=100)
            return res
        """
    )
    analyzer = _QuantumRunAnalyzer(source)
    runs = analyzer.analyze()

    assert len(runs) == 1
    assert runs[0]["input_format"] == normalize_circuit_type("qiskit")
    assert runs[0]["dynamic"] is False


def test_quantum_run_analyzer_aliased_import_and_cirq():
    source = textwrap.dedent(
        """
        from qall import run as qrun
        import cirq

        def execute():
            circuit = cirq.Circuit()
            res = qrun(circuit, shots=50)
            return res
        """
    )
    analyzer = _QuantumRunAnalyzer(source)
    runs = analyzer.analyze()

    assert len(runs) == 1
    assert runs[0]["input_format"] == normalize_circuit_type("cirq")
    assert runs[0]["dynamic"] is False


def test_quantum_run_analyzer_dynamic_or_unknown_type():
    source = textwrap.dedent(
        """
        import qall

        def execute(circuit_unk):
            return qall.run(circuit_unk, shots=10)
        """
    )
    analyzer = _QuantumRunAnalyzer(source)
    runs = analyzer.analyze()

    assert len(runs) == 1
    assert runs[0]["input_format"] is None
    assert runs[0]["dynamic"] is True


def test_extract_quantum_runs_from_local_dependencies():
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
            return qall.run(qc, shots=200)
        """
    )

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
