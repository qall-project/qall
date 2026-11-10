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

import perceval as pcvl

from qall.provider.qc import (
    QuantumContext,
    QuantumWorker,
    quantum_worker,
)


@quantum_worker(
    requirements=["perceval-quandela"],
    input_format="perceval",
    output_format="perceval",
    provider="local",
)
class PercevalLocalQuantumWorker(QuantumWorker):
    """Quantum worker executing Perceval photonic programs using local simulation

    backends (e.g., SLOS, CliffordClifford2).
    """

    def __init__(self) -> None:
        super().__init__()
        self.__backend = None

    def create_context(
        self,
        resource: str,
        context: QuantumContext,
        **kwargs,
    ) -> QuantumContext:
        backend_name = resource if resource else "SLOS"

        self.__backend = pcvl.SimulatedComputer(backend_name)

        return context

    def get_context_status(self, context: str):
        if self.__backend is None:
            raise RuntimeError("No local backend has been initialized yet.")

        return True

    def run(
        self,
        program: Any,
        shots: int,
        context: QuantumContext,
        **kwargs,
    ) -> Any:
        max_shots_per_call = kwargs.get("max_shots_per_call", shots)
        noise_model = kwargs.get("noise", None)

        try:
            if noise_model is not None:
                self.__backend.noise = noise_model

            factory = pcvl.ExecutionFactory(
                computer=self.__backend,
                experiment=program,
                max_shots_per_call=max_shots_per_call,
            )

            results = factory.samples(max_samples=shots)
        finally:
            self.__backend.noise = None

        return results

    def close_context(
        self,
        context: QuantumContext,
        **kwargs,
    ) -> None:
        return context
