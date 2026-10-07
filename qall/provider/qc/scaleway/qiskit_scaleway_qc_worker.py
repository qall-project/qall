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
from uuid import uuid4

from qiskit import QuantumCircuit
from qiskit.result import Result
from qiskit_scaleway import ScalewayProvider

from qorus.provider.qc import (
    QuantumWorker,
    QuantumContext,
    quantum_worker,
)

from .utils import (
    get_session_dedup_from_context,
    list_session_ids_from_context,
    set_session_dedup_in_context,
    add_session_id_in_context,
)


@quantum_worker(
    requirements=["qiskit-scaleway"],
    input_format="qiskit",
    output_format="qiskit",
)
class QiskitScalewayQuantumWorker(QuantumWorker):
    """
    Quantum worker executing Qiskit programs through Scaleway QaaS.
    This class contains provider-specific logic only.
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
        provider = ScalewayProvider(
            project_id=kwargs.get("scaleway_project_id"),
            secret_key=kwargs.get("scaleway_secret_key"),
            url=kwargs.get("scaleway_url"),
        )

        self.__backend = provider.get_backend(resource)

        deduplication_id = get_session_dedup_from_context(context)
        if not deduplication_id:
            deduplication_id = uuid4()
            set_session_dedup_in_context(context, deduplication_id)

        session_id = self.__backend.start_session(
            name=f"{resource}-qorus-session",
            deduplication_id=deduplication_id,
        )

        add_session_id_in_context(context, session_id)

        return context

    def get_context_status(self, context: str):
        if self.__backend is None:
            raise RuntimeError("No session has been created yet.")

        return True

    def run(
        self,
        program: QuantumCircuit,
        shots: int,
        context: QuantumContext,
        **kwargs,
    ) -> Result:
        session_ids = list_session_ids_from_context(context)

        if not session_ids:
            raise RuntimeError("no assigned session")

        result = self.__backend.run(
            program, shots=shots, session_id=session_ids[0]
        ).result()

        return result

    def close_context(
        self,
        context: QuantumContext,
        **kwargs,
    ) -> None:
        session_ids = list_session_ids_from_context(context)

        for session_id in session_ids:
            self.__backend.stop_session(session_id)

        return context
