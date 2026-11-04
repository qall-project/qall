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

from typing import Callable, Optional

from qall.specification import TaskSpec


def task(
    func: Optional[Callable] = None,
    *,
    entrypoint: bool = False,
    **kwargs,
):
    """
    Decorator that turns a function into a qall task.
    Supports both bare and called usage:

        @task
        def a(): ...

        @task()
        def b(): ...

        @task(entrypoint=True, requirements=[...])
        def c(): ...
    """

    def decorator_task(func):
        quantum_resources = {
            "min_qubits": kwargs.pop("min_qubits", 0),
            "min_shots": kwargs.pop("min_shots", 0),
            "min_ops": kwargs.pop("min_ops", 0),
            "qpu_modality": kwargs.pop("qpu_modality", kwargs.pop("modality", None)),
            "qpu_provider": kwargs.pop("qpu_provider", kwargs.pop("provider", None)),
            "qpu_technology": kwargs.pop(
                "qpu_technology", kwargs.pop("technology", None)
            ),
            "qpu_gateset": kwargs.pop("qpu_gateset", kwargs.pop("gateset", None)),
            "qpu_mcm_support": kwargs.pop(
                "qpu_mcm_support", kwargs.pop("mcm_support", False)
            ),
            "qpu_reset_support": kwargs.pop(
                "qpu_reset_support", kwargs.pop("reset_support", False)
            ),
            "qpu_topology": kwargs.pop("qpu_topology", kwargs.pop("topology", None)),
        }

        classical_resources = {
            "min_cpu": kwargs.pop("min_cpu", 0),
            "min_gpu": kwargs.pop("min_gpu", 0),
            "min_ram_gb": kwargs.pop("min_ram_gb", 0),
            "min_vram_gb": kwargs.pop("min_vram_gb", 0),
        }

        return TaskSpec(
            func,
            entrypoint=entrypoint,
            quantum_resources=quantum_resources,
            classical_resources=classical_resources,
            **kwargs,
        )

    if func is not None:
        return decorator_task(func)
    return decorator_task


def workflow(func: Optional[Callable] = None, **kwargs):
    """
    Decorator that turns a function into the entrypoint task of a workflow.

    Supports both bare and called usage:

        @workflow
        async def main(): ...

        @workflow()
        async def main(): ...

        @workflow(requirements=[...])
        async def main(): ...
    """
    kwargs["entrypoint"] = True
    return task(func, **kwargs)
