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
from __future__ import annotations

from qall.specification import WorkerSpec


def quantum_worker(**kwargs):
    """
    Decorator creating a WorkerSpec from a long-lived worker class.

    Example:

        @quantum_worker(
            requirements=["qiskit-scaleway"],
            input_format="qiskit.QiskitCircuit",
            output_format="qiskit.Result",
        )
        class QiskitScalewayQuantumWorker(QuantumWorker):
            ...
    """

    def decorator_worker(cls: type) -> type:
        cls.__qall_worker_spec__ = kwargs

        return WorkerSpec(cls, **kwargs)

    return decorator_worker
