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

from pulser.devices import AnalogDevice, DigitalAnalogDevice, MockDevice

from qall.provider.qc import (
    QuantumContext,
    QuantumWorker,
    quantum_worker,
)


@quantum_worker(
    requirements=["pulser", "pulser-simulation"],
    input_format="pulser",
    output_format="pulser",
    provider="local",
)
class PulserLocalQuantumWorker(QuantumWorker):
    """Quantum worker executing Pulser sequences on local classical emulators

    (QutipEmulator) using virtual/mock devices.
    """

    def __init__(self) -> None:
        super().__init__()
        self.__device = None

    def create_context(
        self,
        resource: str,
        context: QuantumContext,
        **kwargs,
    ) -> QuantumContext:
        devices_map = {
            "MockDevice": MockDevice,
            "AnalogDevice": AnalogDevice,
            "DigitalAnalogDevice": DigitalAnalogDevice,
        }
        self.__device = devices_map.get(resource, MockDevice)

        context.bin_metadata["device"] = self.__device
        context.metadata["device_name"] = getattr(
            self.__device, "name", str(self.__device)
        )

        return context

    def get_context_status(self, context: str):
        if self.__device is None:
            raise RuntimeError("No local device configured.")
        return True

    def run(
        self,
        program: Any,
        shots: int,
        context: QuantumContext,
        **kwargs,
    ) -> Any:
        job_params = kwargs.get("job_params", None)

        if job_params:
            results = []
            for param in job_params:
                n_runs = param.get("runs", shots)
                variables = param.get("variables", None)

                seq = (
                    program.build(**variables)
                    if variables
                    and hasattr(program, "is_parametrized")
                    and program.is_parametrized()
                    else program
                )

                sim = QutipEmulator.from_sequence(seq)
                sim_res = sim.run()
                results.append(sim_res.sample_final_state(N_samples=n_runs))

            return results if len(results) > 1 else results[0]

        variables = kwargs.get("variables", None)
        seq = (
            program.build(**variables)
            if variables
            and hasattr(program, "is_parametrized")
            and program.is_parametrized()
            else program
        )

        sim = QutipEmulator.from_sequence(seq)
        sim_res = sim.run()
        return sim_res.sample_final_state(N_samples=shots)

    def close_context(
        self,
        context: QuantumContext,
        **kwargs,
    ) -> None:
        return context
