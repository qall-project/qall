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
from uuid import uuid4

from cirq_scaleway import ScalewayQuantumService

from qall.provider.qc import (
    QuantumWorker,
    QuantumContext,
    quantum_worker,
)

from qall.provider.qc.scaleway.utils import (
    list_session_ids_from_context,
    add_session_id_in_context,
    set_session_dedup_in_context,
    get_session_dedup_from_context,
)


@quantum_worker(
    requirements=["cirq-scaleway"],
    input_format="cirq",
    output_format="cirq",
)
class CirqScalewayQuantumWorker(QuantumWorker):
    """
    Quantum worker executing Cirq programs through Scaleway QaaS.
    This class contains provider-specific logic only.
    """

    def __init__(
        self,
    ) -> None:
        super().__init__()

        self.__session = None

    def create_context(
        self,
        resource: str,
        context: QuantumContext,
        **kwargs,
    ) -> QuantumContext:
        service = ScalewayQuantumService(
            project_id=kwargs.get("project_id"),
            secret_key=kwargs.get("secret_key"),
            url=kwargs.get("url"),
        )

        device = service.device(resource)

        deduplication_id = get_session_dedup_from_context(context)

        if not deduplication_id:
            deduplication_id = uuid4()
            set_session_dedup_in_context(context, deduplication_id)

        session = device.create_session(
            name=f"{resource.lower()}-qall-session",
            deduplication_id=deduplication_id,
        )
        session.start()

        add_session_id_in_context(context, session.id)

        self.__session = session

        return context

    def get_context_status(self, context: str):
        if self.__session is None:
            raise RuntimeError("No session has been created yet.")

        return True

    def run(
        self,
        program: Any,
        shots: int,
        context: QuantumContext,
        **kwargs,
    ) -> Any:
        session_ids = list_session_ids_from_context(context)

        if not session_ids:
            raise RuntimeError("no assigned session")

        result = self.__session.run(program, repetitions=shots)

        return result

    def close_context(
        self,
        context: QuantumContext,
        **kwargs,
    ) -> None:
        self.__session.stop()

        return context
