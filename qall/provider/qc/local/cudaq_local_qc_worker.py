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

import cudaq

from qall.provider.qc import (
    QuantumContext,
    QuantumWorker,
    quantum_worker,
)


@quantum_worker(
    requirements=["cudaq"],
    input_format="cudaq",
    output_format="cudaq",
    provider="local",
)
class CudaQLocalQuantumWorker(QuantumWorker):
    """Quantum worker executing CUDA-Q programs on local emulator backends

    (e.g., qpp-cpu, density-matrix-cpu, nvidia).
    """

    def __init__(self) -> None:
        super().__init__()
        self.__target = None

    def create_context(
        self,
        resource: str,
        context: QuantumContext,
        **kwargs,
    ) -> QuantumContext:
        self.__target = resource if resource else "qpp-cpu"

        cudaq.set_target(self.__target)

        return context

    def get_context_status(self, context: str):
        if self.__target is None:
            raise RuntimeError("No target has been configured yet.")
        return True

    def run(
        self,
        program: Any,
        shots: int,
        context: QuantumContext,
        **kwargs,
    ) -> Any:
        result = cudaq.sample(program, shots_count=shots, **kwargs)
        return result

    def close_context(
        self,
        context: QuantumContext,
        **kwargs,
    ) -> None:
        if hasattr(cudaq, "reset_target"):
            cudaq.reset_target()
        return context
