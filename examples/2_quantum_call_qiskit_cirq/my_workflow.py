import qall
import qiskit
import cirq

from qiskit.result import Result
from cirq.study.result import ResultDict

from random import randint


@qall.task()
def prepare(x):
    return randint(1, x)


@qall.task(min_qubits=2, requirements=["qiskit", "cirq"])
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
