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
from qiskit import QuantumCircuit
from qiskit.result import Result
from qiskit_aer import AerSimulator

from qall.provider.qc import (
    QuantumWorker,
    QuantumContext,
    quantum_worker,
)


@quantum_worker(
    requirements=["qiskit", "qiskit-aer", "qiskit-qasm3-import"],
    input_format="qiskit",
    output_format="qiskit",
)
class QiskitLocalQuantumWorker(QuantumWorker):
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
        self.__backend = AerSimulator()

        return context

    def get_context_status(self, context: str):
        if self.__backend is None:
            raise RuntimeError("No backend has been created yet.")

        return True

    def run(
        self,
        program: QuantumCircuit,
        shots: int,
        context: QuantumContext,
        **kwargs,
    ) -> Result:
        result = self.__backend.run(program, shots=shots).result()

        return result

    def close_context(
        self,
        context: QuantumContext,
        **kwargs,
    ) -> None:
        return context
