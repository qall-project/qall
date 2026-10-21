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

import perceval as pcvl
import perceval.providers.scaleway as scw

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
    requirements=["perceval-quandela"],
    input_format="perceval",
    output_format="perceval",
)
class PercevalScalewayQuantumWorker(QuantumWorker):
    """
    Quantum worker executing Perceval programs through Scaleway QaaS.
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
        deduplication_id = get_session_dedup_from_context(context)

        if not deduplication_id:
            deduplication_id = uuid4()
            set_session_dedup_in_context(context, deduplication_id)

        max_duration = kwargs.get("max_duration", "59m")
        max_idle_duration = kwargs.get("max_duration", "59m")

        communication_layer = scw.ScalewayCommunicationLayer(
            platform_name=resource,
            project_id=kwargs.get("project_id"),
            token=kwargs.get("secret_key"),
            deduplication_id=deduplication_id,
        )
        self.__backend = pcvl.RemoteComputer(communication_layer)

        session_id = communication_layer._rpc_handler.create_session(
            deduplication_id=deduplication_id,
            max_duration_s=max_duration,
            max_idle_duration=max_idle_duration,
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
        max_shots_per_call = kwargs.get("max_shots_per_call", 10_000)

        factory = pcvl.ExecutionFactory(
            self.__backend, program, max_shots_per_call=max_shots_per_call
        )
        results = factory.samples(max_samples=shots)

        return results

    def close_context(
        self,
        context: QuantumContext,
        **kwargs,
    ) -> None:

        self.__backend._communication_layer._rpc_handler.terminate_session()

        return context
