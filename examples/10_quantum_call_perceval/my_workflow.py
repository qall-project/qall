import qall
import numpy as np

import perceval as pcvl

_RX_THETA = np.pi
_S_PHI = np.pi / 2


@qall.task(min_qubits=2, qpu_modality="", requirements=["perceval-quandela"])
def do_quantum_stuff(size, repeat):
    circuit = pcvl.Experiment(m=6, name="Massive")

    circuit.with_input(pcvl.BasicState("|1,0,1,0,1,0>"))
    circuit.min_detected_photons_filter(2)

    result = qall.run(
        circuit,
        shots=repeat,
        max_shots_per_call=10_000_000,
        noise=pcvl.NoiseModel(
            indistinguishability=0.1,
            g2=0.1,
            transmittance=0.5,
        ),
    )

    return result


@qall.workflow()
def main():
    b = []
    for _ in range(2):
        b.append(do_quantum_stuff(5, 1))

    return b
