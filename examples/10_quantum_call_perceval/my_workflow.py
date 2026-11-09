import qall
import numpy as np

import perceval as pcvl

_RX_THETA = np.pi
_S_PHI = np.pi / 2


@qall.task(min_qubits=2, qpu_modality="", requirements=["perceval-quandela"])
def do_quantum_stuff(size, repeat):

    massive_circuit = (
        pcvl.Circuit(m=6, name="Massive")
        // (0, pcvl.BS.H())
        // (0, pcvl.BS.Rx(theta=_RX_THETA))
        // (2, pcvl.BS.H())
        // (2, pcvl.BS.Rx(theta=_RX_THETA))
        // (2, pcvl.BS.H())
        // (2, pcvl.BS.Rx(theta=_RX_THETA))
        // (3, pcvl.PS(phi=_S_PHI))
        // (4, pcvl.BS.H())
        // (3, pcvl.PS(phi=_S_PHI))
        // (4, pcvl.BS.H())
        // (2, pcvl.BS.Rx(theta=_RX_THETA))
        // (4, pcvl.BS.H())
        // (3, pcvl.BS.Rx(theta=_RX_THETA))
        // (0, pcvl.BS.H())
        // (0, pcvl.BS.Rx(theta=_RX_THETA))
        // (2, pcvl.BS.H())
        // (2, pcvl.BS.Rx(theta=_RX_THETA))
        // (1, pcvl.BS.H())
        // (2, pcvl.BS.Rx(theta=_RX_THETA))
    )

    return results


@qall.workflow()
def main():
    b = []
    for _ in range(2):
        b.append(do_quantum_stuff(5, 1))

    return b
