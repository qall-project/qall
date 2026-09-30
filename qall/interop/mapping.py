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
from typing import Any
from qio.core import QuantumProgram, QuantumProgramResult

CIRCUIT_TYPE_QISKIT = "qiskit.QuantumCircuit"
CIRCUIT_TYPE_CIRQ = "cirq.Circuit"
CIRCUIT_TYPE_CUDAQ = "cudaq.PyKernel"
CIRCUIT_TYPE_MIMIQ = "mimiqcircuits.Circuit"
CIRCUIT_TYPE_QASM2 = "qasm2"
CIRCUIT_TYPE_QIO = "qio.QuantumProgram"

RESULT_TYPE_QISKIT = "qiskit.result.Result"
RESULT_TYPE_CIRQ = "cirq.Result"
RESULT_TYPE_CUDAQ = "cudaq.SampleResult"
RESULT_TYPE_MIMIQ = "mimiqcircuits.QCSResults"
RESULT_TYPE_QIO = "qio.QuantumProgramResult"

QUANTUM_CIRCUIT_TYPE_MAPPING = {
    "qiskit": CIRCUIT_TYPE_QISKIT,
    "qiskit.QuantumCircuit": CIRCUIT_TYPE_QISKIT,
    "qiskit.circuit.quantumcircuit.QuantumCircuit": CIRCUIT_TYPE_QISKIT,
    "cirq": CIRCUIT_TYPE_CIRQ,
    "cirq.Circuit": CIRCUIT_TYPE_CIRQ,
    "cirq.circuits.circuit.Circuit": CIRCUIT_TYPE_CIRQ,
    "cudaq": CIRCUIT_TYPE_CUDAQ,
    "cudaq.PyKernel": CIRCUIT_TYPE_CUDAQ,
    "mimiq": CIRCUIT_TYPE_MIMIQ,
    "mimiqcircuits": CIRCUIT_TYPE_MIMIQ,
    "mimiqcircuits.Circuit": CIRCUIT_TYPE_MIMIQ,
    "qasm2": CIRCUIT_TYPE_QASM2,
    "qio": CIRCUIT_TYPE_QIO,
    "qio.QuantumProgram": CIRCUIT_TYPE_QIO,
}

QUANTUM_RESULT_TYPE_MAPPING = {
    "qiskit": RESULT_TYPE_QISKIT,
    "qiskit.result.Result": RESULT_TYPE_QISKIT,
    "qiskit.result.result.Result": RESULT_TYPE_QISKIT,
    "cirq": RESULT_TYPE_CIRQ,
    "cirq.Result": RESULT_TYPE_CIRQ,
    "cirq.study.result.Result": RESULT_TYPE_CIRQ,
    "cirq.study.result.ResultDict": RESULT_TYPE_CIRQ,
    "cudaq": RESULT_TYPE_CUDAQ,
    "cudaq.SampleResult": RESULT_TYPE_CUDAQ,
    "mimiq": RESULT_TYPE_MIMIQ,
    "mimiqcircuits": RESULT_TYPE_MIMIQ,
    "mimiqcircuits.QCSResults": RESULT_TYPE_MIMIQ,
    "qio": RESULT_TYPE_QIO,
    "qio.QuantumProgramResult": RESULT_TYPE_QIO,
}


def normalize_circuit_type(target: Any) -> str:
    if isinstance(target, str):
        raw_type = target
    else:
        t = type(target)
        raw_type = f"{t.__module__}.{t.__name__}"

    return QUANTUM_CIRCUIT_TYPE_MAPPING.get(raw_type, raw_type)


def normalize_result_type(target: Any) -> str:
    if isinstance(target, str):
        raw_type = target
    else:
        t = type(target)
        raw_type = f"{t.__module__}.{t.__name__}"

    return QUANTUM_RESULT_TYPE_MAPPING.get(raw_type, raw_type)


def native_program_to_qio_program(program: Any) -> QuantumProgram:
    if isinstance(program, QuantumProgram):
        return program

    c_type = normalize_circuit_type(program)

    if c_type == CIRCUIT_TYPE_QISKIT:
        return QuantumProgram.from_qiskit_circuit(program)
    elif c_type == CIRCUIT_TYPE_CIRQ:
        return QuantumProgram.from_cirq_circuit(program)
    elif c_type == CIRCUIT_TYPE_CUDAQ:
        return QuantumProgram.from_cudaq_kernel(program)
    elif c_type == CIRCUIT_TYPE_MIMIQ:
        return QuantumProgram.from_mimiq_circuit(program)

    return program


def qio_program_to_native_program(program: QuantumProgram, target_format: str) -> Any:
    c_type = normalize_circuit_type(target_format)

    if c_type == CIRCUIT_TYPE_QISKIT:
        return program.to_qiskit_circuit()
    elif c_type == CIRCUIT_TYPE_CIRQ:
        return program.to_cirq_circuit()
    elif c_type == CIRCUIT_TYPE_CUDAQ:
        return program.to_cudaq_kernel()
    elif c_type == CIRCUIT_TYPE_MIMIQ:
        return program.to_mimiq_circuit()
    elif c_type == CIRCUIT_TYPE_QASM2:
        return program.to_qasm2_circuit()
    return program


def native_result_to_qio_result(result: Any) -> QuantumProgramResult:
    if isinstance(result, QuantumProgramResult):
        return result

    r_type = normalize_result_type(result)

    if r_type == RESULT_TYPE_QISKIT:
        return QuantumProgramResult.from_qiskit_result(result)
    elif r_type == RESULT_TYPE_CIRQ:
        return QuantumProgramResult.from_cirq_result(result)
    elif r_type == RESULT_TYPE_CUDAQ:
        return QuantumProgramResult.from_cudaq_sample_result(result)
    elif r_type == RESULT_TYPE_MIMIQ:
        return QuantumProgramResult.from_mimiq_qcsr(result)

    return result


def qio_result_to_native_result(
    result: QuantumProgramResult, target_format: str
) -> Any:
    r_type = normalize_result_type(target_format)

    if r_type == RESULT_TYPE_QISKIT:
        return result.to_qiskit_result()
    elif r_type == RESULT_TYPE_CIRQ:
        return result.to_cirq_result()
    elif r_type == RESULT_TYPE_CUDAQ:
        return result.to_cudaq_sample_result()
    elif r_type == RESULT_TYPE_MIMIQ:
        return result.to_mimiq_qcsr()

    return result
