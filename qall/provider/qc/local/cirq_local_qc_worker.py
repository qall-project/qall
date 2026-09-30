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
from qsimcirq import QSimSimulator
from cirq import Circuit, Result

from qall.provider.qc import (
    QuantumWorker,
    QuantumContext,
    quantum_worker,
)


@quantum_worker(
    requirements=["cirq", "qsimcirq", "ply"],
    input_format="cirq",
    output_format="cirq",
)
class CirqLocalQuantumWorker(QuantumWorker):
    """
    Quantum worker executing Qiskit programs with Aer backend.
    """

    def __init__(
        self,
    ) -> None:
        super().__init__()
        self.__backend = None

    def create_context(
        self,
        resource: str,
        context: QuantumContext,
        **kwargs,
    ) -> QuantumContext:
        self.__backend = QSimSimulator()

        return context

    def get_context_status(self, context: str):
        if self.__backend is None:
            raise RuntimeError("No backend has been created yet.")

        return True

    def run(
        self,
        program: Circuit,
        shots: int,
        context: QuantumContext,
        **kwargs,
    ) -> Result:
        result = self.__backend.run(program, repetitions=shots)
        result._params = None

        return result

    def close_context(
        self,
        context: QuantumContext,
        **kwargs,
    ) -> None:
        return context
