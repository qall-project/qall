import qall
import numpy as np

from pulser import Pulse, Sequence, BlackmanWaveform, RampWaveform
from pulser.register import Register


@qall.task(min_qubits=2, qpu_modality="analog", requirements=["pulser", "numpy"])
def do_quantum_stuff(size, repeat):
    device = qall.context["device"]

    register = Register.square(2, spacing=6.0).with_automatic_layout(device)
    seq = Sequence(register, device)

    seq.declare_channel("rydberg_global", "rydberg_global")
    t = seq.declare_variable("t", dtype=int)

    amp_wf = BlackmanWaveform(t, np.pi / 2)
    det_wf = RampWaveform(t, -5, 5)
    seq.add(Pulse(amp_wf, det_wf, 0), "rydberg_global")

    results = qall.run(
        job_params=[
            {
                "runs": 2,
                "variables": {"t": 500},
            },
            {"runs": 3, "variables": {"t": 500}},
        ],
        wait=True,
    )

    return results


@qall.workflow()
def main():
    b = []
    for _ in range(2):
        b.append(do_quantum_stuff(5, 1))

    return b
