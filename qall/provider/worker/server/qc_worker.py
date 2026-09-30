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
from abc import ABC, abstractmethod
from typing import Any

from ..context import QuantumContext, QuantumCapabilities


class QuantumWorker(ABC):
    """
    Provider-facing interface for a quantum execution worker.

    A QuantumWorker is responsible for translating a canonical quantum
    program into a provider-specific execution and translating the result
    back into a canonical representation.

    The worker does not perform resource scheduling.
    """

    __capabilities: QuantumCapabilities

    @abstractmethod
    def create_context(
        self,
        resource: str,
        context: QuantumContext,
        **kwargs,
    ) -> QuantumContext:
        """
        Create the initial execution context.

        This does not necessarily create a provider-side session.
        Session creation can be lazy on the first run().
        """
        raise NotImplementedError

    @abstractmethod
    def run(
        self,
        program: Any,
        shots: int,
        context: QuantumContext,
        **kwargs,
    ) -> Any:
        """
        Execute a quantum program.

        The returned context may contain updated provider session information.
        """
        raise NotImplementedError

    @abstractmethod
    def close_context(
        self,
        context: QuantumContext,
        **kwargs,
    ) -> QuantumContext:
        """
        Close the execution context and release provider resources.
        """
        raise NotImplementedError

    @property
    def capabilities(self) -> QuantumCapabilities:
        """
        Return the capabilities of this worker.
        """
        return self.__capabilities

    def set_capabilities(self, input_format: str, output_format: str):
        self.__capabilities = QuantumCapabilities(
            input_format=input_format,
            output_format=output_format,
        )
