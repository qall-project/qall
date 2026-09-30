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

import logging

from typing import Any

from qall.provider.worker import QuantumWorkerManager

logger = logging.getLogger(__name__)

__qw_manager: QuantumWorkerManager | None = None


def create_quantum_worker_manager(
    worker_addresses: list[str],
) -> QuantumWorkerManager:
    global __qw_manager
    if __qw_manager:
        raise RuntimeError("QuantumWorkerManager has been already initialized.")

    if worker_addresses:
        qw_manager = QuantumWorkerManager()

        for address in worker_addresses:
            qw_manager.register(address=address)

    __qw_manager = qw_manager

    return __qw_manager


def create_quantum_run(
    program: Any,
    shots: int,
    **kwargs,
) -> Any:
    global __qw_manager
    if __qw_manager is None:
        raise RuntimeError("QuantumWorkerManager has not been initialized.")

    return __qw_manager.run(
        program=program,
        shots=shots,
        **kwargs,
    )


def stop_quantum_worker_manager():
    global __qw_manager

    if __qw_manager is None:
        # raise RuntimeError("QuantumWorkerManager has not been initialized.")
        logger.warning("No QuantumWorkerManager to stop.")
        return

    __qw_manager.stop()

    __qw_manager = None
