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

from pulser import QPUBackend
from pulser_scaleway import ScalewayProvider

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
    requirements=["pulser-scaleway"],
    input_format="pulser",
    output_format="pulser",
    provider="scaleway",
)
class PulserScalewayQuantumWorker(QuantumWorker):
    """
    Quantum worker executing Pulser programs through Scaleway QaaS.
    This class contains provider-specific logic only.
    """

    def __init__(
        self,
    ) -> None:
        super().__init__()

        self.__connection = None
        self.__is_emu = False

    def create_context(
        self,
        resource: str,
        context: QuantumContext,
        **kwargs,
    ) -> QuantumContext:
        self.__is_emu = resource.startswith("EMU_")

        deduplication_id = get_session_dedup_from_context(context)

        if not deduplication_id:
            deduplication_id = uuid4()
            set_session_dedup_in_context(context, deduplication_id)

        project_id = kwargs.get("project_id")
        secret_key = kwargs.get("secret_key")
        url = kwargs.get("url")

        provider = ScalewayProvider(
            project_id=project_id,
            secret_key=secret_key,
            url=url,
            deduplication_id=deduplication_id,
        )

        self.__connection = provider

        if self.__is_emu:
            client = self.__connection._client

            platforms = client.list_platforms(name=resource)

            assert platforms
            assert len(platforms) == 1

            max_duration = kwargs.get("max_duration", "59m")
            max_idle_duration = kwargs.get("max_duration", "59m")

            active_session = client.create_session(
                platform_id=platforms[0].id,
                deduplication_id=deduplication_id,
                max_duration=max_duration,
                max_idle_duration=max_idle_duration,
            )

            add_session_id_in_context(context, active_session.id)

        return context

    def get_context_status(self, context: str):
        if self.__connection is None:
            raise RuntimeError("No session has been created yet.")

        return True

    def run(
        self,
        program: Any,
        shots: int,
        context: QuantumContext,
        **kwargs,
    ) -> Any:
        backend = QPUBackend(sequence=program, connection=self.__connection)

        if self.__is_emu:
            session_ids = list_session_ids_from_context(context)

            if not session_ids:
                raise RuntimeError("no assigned session")

        job_params = kwargs.get("job_params", None)
        wait = kwargs.get("wait", True)

        if job_params:
            results = backend.run(job_params=job_params, wait=wait)
        else:
            variables = kwargs.get("variables", None)

            results = backend.run(
                job_params=[{"runs": shots, "variables": variables}],
                wait=wait,
            )

        return results

    def close_context(
        self,
        context: QuantumContext,
        **kwargs,
    ) -> None:
        if self.__is_emu:
            session_ids = list_session_ids_from_context(context)

            for session_id in session_ids:
                self.__connection._client.terminate_session(session_id)

            return context
