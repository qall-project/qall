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

        @task(entrypoint=True, piprequirements=[...])
        def c(): ...
    """

    def decorator_task(func):
        min_qubits = kwargs.pop("min_qubits", None)
        min_cpu = kwargs.pop("min_cpu", None)

        quantum_resources = {"min_qubits": min_qubits} if min_qubits else {}
        classical_resources = {"min_cpu": min_cpu} if min_cpu else {}

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

        @workflow(piprequirements=[...])
        async def main(): ...
    """
    kwargs["entrypoint"] = True
    return task(func, **kwargs)
