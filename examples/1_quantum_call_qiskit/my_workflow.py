import qorus
import qiskit

from random import randint


@qorus.task()
def prepare(x):
    return randint(1, x)


@qorus.task(min_qubits=2, piprequirements=["qiskit"])
def do_quantum_stuff(size, repeat):
    qc = qiskit.QuantumCircuit(size)
    qc.h(0)

    for i in range(1, size):
        qc.cx(i - 1, i)

    qc.measure_all()

    pre_warm = qorus.run(qc, shots=100)

    r = 0
    for _ in range(repeat):
        result = qorus.run(qc, shots=10)
        r += result.get_counts().get("0" * size, 0)

    return r


@qorus.workflow()
def main():
    a = prepare(5)

    b = []
    for _ in range(3):
        b.append(do_quantum_stuff(a, 10))

    return b
