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
from pulser_simulation import QutipBackendV2, QutipConfig

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
    """Quantum worker executing Pulser sequences on local QutipBackendV2 emulator."""

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
            "LOCAL-PULSER-MOCK": MockDevice,
            "LOCAL-PULSER-ANALOG": AnalogDevice,
            "LOCAL-PULSER-DIGITAL-ANALOG": DigitalAnalogDevice,
        }
        self.__device = devices_map.get(resource, MockDevice)

        context.bin_metadata["device"] = self.__device
        context.metadata["device_name"] = self.__device.name
        return context

    def get_context_status(self, context: str):
        if self.__device is None:
            raise RuntimeError("No local device configured.")
        return True

    def _run_single(
        self, program: Any, n_shots: int, variables: dict | None
    ) -> dict[str, int]:
        seq = (
            program.build(**variables)
            if variables
            and hasattr(program, "is_parametrized")
            and program.is_parametrized()
            else program
        )
        config = QutipConfig(default_num_shots=n_shots)
        sim = QutipBackendV2(seq, config=config)
        sim_res = sim.run()

        return dict(sim_res.final_bitstrings)

    def sample(
        self,
        program: Any,
        shots: int,
        context: QuantumContext,
        **kwargs,
    ) -> Any:
        job_params = kwargs.get("job_params", None)

        if job_params:
            results = [
                self._run_single(
                    program,
                    n_shots=param.get("runs", shots),
                    variables=param.get("variables", None),
                )
                for param in job_params
            ]
            return results if len(results) > 1 else results[0]

        return self._run_single(
            program,
            n_shots=shots,
            variables=kwargs.get("variables", None),
        )

    def close_context(
        self,
        context: QuantumContext,
        **kwargs,
    ) -> None:
        return context
