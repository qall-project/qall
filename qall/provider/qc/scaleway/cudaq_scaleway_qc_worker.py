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

import cudaq

from scaleway_qaas_client.v1alpha1 import QaaSClient

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
    requirements=["cudaq", "scaleway-qaas-client"],
    input_format="cudaq",
    output_format="cudaq",
)
class CudaQScalewayQuantumWorker(QuantumWorker):
    """
    Quantum worker executing CUDA-Q programs through Scaleway QaaS.
    This class contains provider-specific logic only.
    """

    def __init__(
        self,
    ) -> None:
        super().__init__()

        self.__client = None

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

        project_id = (kwargs.get("project_id"),)
        secret_key = (kwargs.get("secret_key"),)
        url = (kwargs.get("url"),)

        cudaq.set_target(
            "scaleway",
            project_id=project_id,
            secret_key=secret_key,
            url=url,
            max_duration=kwargs.get("max_duration", "59m"),
            max_idle_duration=kwargs.get("max_duration", "59m"),
            deduplication_id=deduplication_id,
            machine=resource,
        )

        # As CUDA-Q cannot manage session paradigm,
        # we must manage via raw QaaS client to keep trace of the session
        self.__client = QaaSClient(
            project_id=project_id, secret_key=secret_key, url=url
        )

        platforms = self.__client.list_platforms(name=resource)

        assert platforms
        assert len(platforms) == 1

        active_session = self.__client.create_session(
            platform_id=platforms[0].id, deduplication_id=deduplication_id
        )

        add_session_id_in_context(context, active_session.id)

        return context

    def get_context_status(self, context: str):
        if self.__client is None:
            raise RuntimeError("No session has been created yet.")

        return True

    def run(
        self,
        program: Any,
        shots: int,
        context: QuantumContext,
        **kwargs,
    ) -> Any:
        result = cudaq.sample(kernel=program, shots_count=shots)

        return result

    def close_context(
        self,
        context: QuantumContext,
        **kwargs,
    ) -> None:
        session_ids = list_session_ids_from_context(context)

        for session_id in session_ids:
            self.__client.terminate_session(session_id)

        return context
