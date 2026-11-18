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

_CIRCUIT_TYPE_QISKIT_CIRCUIT = "qiskit.QuantumCircuit"
_CIRCUIT_TYPE_CIRQ_CIRCUIT = "cirq.Circuit"
_CIRCUIT_TYPE_CUDAQ_KERNEL = "cudaq.PyKernel"
_CIRCUIT_TYPE_PERCEVAL_EXPERIMENT = "perceval.Experiment"
_CIRCUIT_TYPE_PERCEVAL_CIRCUIT = "perceval.Circuit"
_CIRCUIT_TYPE_PULSER_SEQUENCE = "pulser.Sequence"
_CIRCUIT_TYPE_MIMIQ_CIRCUIT = "mimiqcircuits.Circuit"
_CIRCUIT_TYPE_QASM2 = "qasm2"
_CIRCUIT_TYPE_QASM3 = "qasm3"
_CIRCUIT_TYPE_QIO_PROGRAM = "qio.QuantumProgram"

_RESULT_TYPE_QISKIT = "qiskit.result.Result"
_RESULT_TYPE_CIRQ = "cirq.Result"
_RESULT_TYPE_PERCEVAL = "perceval.Result"
_RESULT_TYPE_PULSER = "pulser.Result"
_RESULT_TYPE_CUDAQ = "cudaq.SampleResult"
_RESULT_TYPE_MIMIQ = "mimiqcircuits.QCSResults"
_RESULT_TYPE_QIO = "qio.QuantumProgramResult"

_QUANTUM_CIRCUIT_TYPE_MAPPING = {
    "qiskit": _CIRCUIT_TYPE_QISKIT_CIRCUIT,
    "qiskit.QuantumCircuit": _CIRCUIT_TYPE_QISKIT_CIRCUIT,
    "qiskit.circuit.quantumcircuit.QuantumCircuit": _CIRCUIT_TYPE_QISKIT_CIRCUIT,
    "cirq": _CIRCUIT_TYPE_CIRQ_CIRCUIT,
    "cirq.Circuit": _CIRCUIT_TYPE_CIRQ_CIRCUIT,
    "cirq.circuits.circuit.Circuit": _CIRCUIT_TYPE_CIRQ_CIRCUIT,
    "cudaq": _CIRCUIT_TYPE_CUDAQ_KERNEL,
    "cudaq.PyKernel": _CIRCUIT_TYPE_CUDAQ_KERNEL,
    "mimiq": _CIRCUIT_TYPE_MIMIQ_CIRCUIT,
    "mimiqcircuits": _CIRCUIT_TYPE_MIMIQ_CIRCUIT,
    "mimiqcircuits.Circuit": _CIRCUIT_TYPE_MIMIQ_CIRCUIT,
    "qasm2": _CIRCUIT_TYPE_QASM2,
    "qasm3": _CIRCUIT_TYPE_QASM3,
    "qio": _CIRCUIT_TYPE_QIO_PROGRAM,
    "qio.QuantumProgram": _CIRCUIT_TYPE_QIO_PROGRAM,
    "pulser": _CIRCUIT_TYPE_PULSER_SEQUENCE,
    "pulser.Sequence": _CIRCUIT_TYPE_PULSER_SEQUENCE,
    "perceval": _CIRCUIT_TYPE_PERCEVAL_EXPERIMENT,
    "perceval.Experiment": _CIRCUIT_TYPE_PERCEVAL_EXPERIMENT,
    "perceval.Circuit": _CIRCUIT_TYPE_PERCEVAL_CIRCUIT,
}

_QUANTUM_RESULT_TYPE_MAPPING = {
    "qiskit": _RESULT_TYPE_QISKIT,
    "qiskit.result.Result": _RESULT_TYPE_QISKIT,
    "qiskit.result.result.Result": _RESULT_TYPE_QISKIT,
    "cirq": _RESULT_TYPE_CIRQ,
    "cirq.Result": _RESULT_TYPE_CIRQ,
    "cirq.study.result.Result": _RESULT_TYPE_CIRQ,
    "cirq.study.result.ResultDict": _RESULT_TYPE_CIRQ,
    "cudaq": _RESULT_TYPE_CUDAQ,
    "cudaq.SampleResult": _RESULT_TYPE_CUDAQ,
    "mimiq": _RESULT_TYPE_MIMIQ,
    "mimiqcircuits": _RESULT_TYPE_MIMIQ,
    "mimiqcircuits.QCSResults": _RESULT_TYPE_MIMIQ,
    "qio": _RESULT_TYPE_QIO,
    "qio.QuantumProgramResult": _RESULT_TYPE_QIO,
    "pulser": _RESULT_TYPE_PULSER,
    "pulser.Result": _RESULT_TYPE_PULSER,
    "perceval": _RESULT_TYPE_PERCEVAL,
    "perceval.Result": _RESULT_TYPE_PERCEVAL,
}


def normalize_circuit_type(target: Any) -> str:
    if isinstance(target, str):
        raw_type = target
    else:
        t = type(target)
        raw_type = f"{t.__module__}.{t.__name__}"

    return _QUANTUM_CIRCUIT_TYPE_MAPPING.get(raw_type, raw_type)


def normalize_result_type(target: Any) -> str:
    if isinstance(target, str):
        raw_type = target
    else:
        t = type(target)
        raw_type = f"{t.__module__}.{t.__name__}"

    return _QUANTUM_RESULT_TYPE_MAPPING.get(raw_type, raw_type)


def native_program_to_qio_program(program: Any) -> QuantumProgram:
    if isinstance(program, QuantumProgram):
        return program

    c_type = normalize_circuit_type(program)

    if c_type == _CIRCUIT_TYPE_QISKIT_CIRCUIT:
        return QuantumProgram.from_qiskit_circuit(program)
    elif c_type == _CIRCUIT_TYPE_CIRQ_CIRCUIT:
        return QuantumProgram.from_cirq_circuit(program)
    elif c_type == _CIRCUIT_TYPE_CUDAQ_KERNEL:
        return QuantumProgram.from_cudaq_kernel(program)
    elif c_type == _CIRCUIT_TYPE_MIMIQ_CIRCUIT:
        return QuantumProgram.from_mimiq_circuit(program)
    elif c_type == _CIRCUIT_TYPE_PERCEVAL_EXPERIMENT:
        return QuantumProgram.from_perceval_experiment(program)
    elif c_type == _CIRCUIT_TYPE_PERCEVAL_CIRCUIT:
        return QuantumProgram.from_perceval_circuit(program)
    elif c_type == _CIRCUIT_TYPE_PULSER_SEQUENCE:
        return QuantumProgram.from_pulser_sequence(program)

    return program


def qio_program_to_native_program(program: QuantumProgram, target_format: str) -> Any:
    c_type = normalize_circuit_type(target_format)

    if c_type == _CIRCUIT_TYPE_QISKIT_CIRCUIT:
        return program.to_qiskit_circuit()
    elif c_type == _CIRCUIT_TYPE_CIRQ_CIRCUIT:
        return program.to_cirq_circuit()
    elif c_type == _CIRCUIT_TYPE_CUDAQ_KERNEL:
        return program.to_cudaq_kernel()
    elif c_type == _CIRCUIT_TYPE_MIMIQ_CIRCUIT:
        return program.to_mimiq_circuit()
    elif c_type == _CIRCUIT_TYPE_QASM2:
        return program.to_qasm2_circuit()
    elif c_type == _CIRCUIT_TYPE_PERCEVAL_EXPERIMENT:
        return program.to_perceval_experiment()
    elif c_type == _CIRCUIT_TYPE_PERCEVAL_CIRCUIT:
        return program.to_perceval_circuit()
    elif c_type == _CIRCUIT_TYPE_PULSER_SEQUENCE:
        return program.to_pulser_sequence()

    return program


def native_result_to_qio_result(result: Any) -> QuantumProgramResult:
    if isinstance(result, QuantumProgramResult):
        return result

    r_type = normalize_result_type(result)

    if r_type == _RESULT_TYPE_QISKIT:
        return QuantumProgramResult.from_qiskit_result(result)
    elif r_type == _RESULT_TYPE_CIRQ:
        return QuantumProgramResult.from_cirq_result(result)
    elif r_type == _RESULT_TYPE_CUDAQ:
        return QuantumProgramResult.from_cudaq_sample_result(result)
    elif r_type == _RESULT_TYPE_MIMIQ:
        return QuantumProgramResult.from_mimiq_qcsr(result)
    elif r_type == _RESULT_TYPE_PERCEVAL:
        return QuantumProgramResult.from_perceval_result(result)
    elif r_type == _RESULT_TYPE_PULSER:
        return QuantumProgramResult.from_pulser_result(result)

    return result


def qio_result_to_native_result(
    result: QuantumProgramResult, target_format: str
) -> Any:
    r_type = normalize_result_type(target_format)

    if r_type == _RESULT_TYPE_QISKIT:
        return result.to_qiskit_result()
    elif r_type == _RESULT_TYPE_CIRQ:
        return result.to_cirq_result()
    elif r_type == _RESULT_TYPE_CUDAQ:
        return result.to_cudaq_sample_result()
    elif r_type == _RESULT_TYPE_MIMIQ:
        return result.to_mimiq_qcsr()
    elif r_type == _RESULT_TYPE_PERCEVAL:
        return result.to_perceval_result()
    elif r_type == _RESULT_TYPE_PULSER:
        return result.to_pulser_result()

    return result
