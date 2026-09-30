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
from dataclasses import dataclass

from typing import Any, Optional

from qall.interop.mapping import normalize_circuit_type

from ..context import QuantumContext, QuantumCapabilities
from .grpc_client import QuantumWorkerClient


@dataclass
class _RegisteredWorker:
    client: QuantumWorkerClient
    capabilities: QuantumCapabilities
    address: str


class QuantumWorkerManager:

    def __init__(self, context: Optional[QuantumContext] = None):
        self.__workers: list[_RegisteredWorker] = []
        self.__context = context if context else QuantumContext()

    def register(
        self,
        address: str,
        credentials=None,
    ) -> None:

        client = QuantumWorkerClient(
            address=address,
            credentials=credentials,
        )

        capabilities = client.get_capabilities()

        self.__workers.append(
            _RegisteredWorker(
                client=client,
                address=address,
                capabilities=capabilities,
            )
        )

        context = client.create_context(self.__context)

        if context:
            self.__context = context

    def _resolve(
        self,
        input_format: str,
    ) -> _RegisteredWorker:
        candidates = []

        for w in self.__workers:
            capabilities = w.capabilities

            if input_format != capabilities.input_format:
                continue

            candidates.append(w)

        if not candidates:
            raise RuntimeError(f"No worker found for input format: {input_format}")

        return candidates[0]

    def run(self, program: Any, shots: int, **kwargs) -> Any:
        input_format = normalize_circuit_type(program)

        worker = self._resolve(input_format=input_format)

        result, context = worker.client.run(
            program=program,
            shots=shots,
            context=self.__context,
            output_format=worker.capabilities.output_format,
            **kwargs,
        )

        if context:
            self.__context = context

        return result

    def stop(self):
        for w in self.__workers:
            w.client.close_context(self.__context)
