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

from qiskit_scaleway import ScalewayProvider

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

from datetime import datetime
from qiskit.providers import JobStatus


def sanitize_qiskit_result(result):
    if result is None:
        return result

    if hasattr(result, "status"):
        if isinstance(result.status, JobStatus) or hasattr(result.status, "name"):
            result.status = result.status.name
        elif not isinstance(result.status, (str, type(None))):
            result.status = str(result.status)

    if hasattr(result, "date") and result.date is not None:
        if isinstance(result.date, datetime):
            result.date = result.date.isoformat()
        elif not isinstance(result.date, str):
            result.date = str(result.date)

    if hasattr(result, "results") and result.results:
        for exp in result.results:
            if hasattr(exp, "status") and (
                isinstance(exp.status, JobStatus) or hasattr(exp.status, "name")
            ):
                exp.status = exp.status.name
            if hasattr(exp, "date") and isinstance(exp.date, datetime):
                exp.date = exp.date.isoformat()

    return result


@quantum_worker(
    requirements=["qiskit-scaleway", "qiskit-qasm3-import"],
    input_format="qiskit",
    output_format="qiskit",
    provider="scaleway",
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
            project_id=kwargs.get("project_id"),
            secret_key=kwargs.get("secret_key"),
            url=kwargs.get("url"),
        )

        self.__backend = provider.get_backend(resource)

        deduplication_id = get_session_dedup_from_context(context)

        if not deduplication_id:
            deduplication_id = str(uuid4())
            set_session_dedup_in_context(context, deduplication_id)

        session_id = self.__backend.start_session(
            name=f"{resource.lower()}-qall-session",
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
        program: Any,
        shots: int,
        context: QuantumContext,
        **kwargs,
    ) -> Any:
        session_ids = list_session_ids_from_context(context)

        if not session_ids:
            raise RuntimeError("no assigned session")

        result = self.__backend.run(
            program, shots=shots, session_id=session_ids[0]
        ).result()

        result = sanitize_qiskit_result(result)
        print("result", result)

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
