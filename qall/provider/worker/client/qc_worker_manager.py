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

from qall.interop.mapping import normalize_circuit_type, is_circuit_convertible

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

    @property
    def context(self) -> QuantumContext:
        return self.__context

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

    def _resolve(self, input_format: str) -> _RegisteredWorker:
        candidates = [
            w
            for w in self.__workers
            if is_circuit_convertible(input_format, w.capabilities.input_format)
        ]

        if not candidates:
            raise RuntimeError(
                f"No worker compatible with client circuit format: {input_format}"
            )

        for w in candidates:
            if normalize_circuit_type(w.capabilities.input_format) == input_format:
                return w

        return candidates[0]

    def sample(self, program: Any, shots: int, **kwargs) -> Any:
        input_format = normalize_circuit_type(program)

        worker = self._resolve(input_format=input_format)

        result, context = worker.client.sample(
            program=program,
            shots=shots,
            context=self.__context,
            **kwargs,
        )

        if context:
            self.__context = context

        return result

    def estimate(self, program: Any, shots: int, **kwargs) -> Any:
        input_format = normalize_circuit_type(program)

        worker = self._resolve(input_format=input_format)

        result, context = worker.client.estimate(
            program=program,
            shots=shots,
            context=self.__context,
            **kwargs,
        )

        if context:
            self.__context = context

        return result

    def stop(self):
        for w in self.__workers:
            w.client.close_context(self.__context)
