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
import os
import platform

from typing import List

from qall.object import (
    CpuSpec,
    QpuModality,
    QpuSpec,
    ResourcePrice,
    QpuTechnology,
    QpuTopology,
    QpuType,
    Resource,
    ResourceAvailability,
)


def get_local_resource() -> Resource:
    cores = os.cpu_count() or 1

    return Resource(
        id="localhost",
        name="localhost",
        provider="local",
        availability=ResourceAvailability.available,
        cpu=CpuSpec(
            model_name="local-cpu",
            available_cores=cores,
            available_memory_gb=16,
        ),
        gpu=None,
        price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
    )


def get_local_qpu_resources() -> List[Resource]:
    return [
        Resource(
            id="local-aer-emulator",
            name="LOCAL-AER",
            provider="local",
            availability=ResourceAvailability.available,
            qpu=QpuSpec(
                available_qubits=32,
                max_shots=100000,
                modality=QpuModality.gate_based,
                topology=QpuTopology.all_to_all,
                technology=QpuTechnology.unknown,
                gateset=["cx", "cz", "rz", "rx", "h", "x", "y", "z", "s", "t"],
                model_name="Qiskit Aer Simulator",
                type=QpuType.emulator,
                bookable=False,
                mcm_support=True,
                reset_support=True,
            ),
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
        ),
        Resource(
            id="local-qsim-emulator",
            name="LOCAL-QSIM",
            provider="local",
            availability=ResourceAvailability.available,
            qpu=QpuSpec(
                available_qubits=32,
                max_shots=100000,
                modality=QpuModality.gate_based,
                topology=QpuTopology.all_to_all,
                technology=QpuTechnology.unknown,
                gateset=["cz", "rz", "rx", "h", "x"],
                model_name="Cirq QSim Simulator",
                type=QpuType.emulator,
                bookable=False,
                mcm_support=True,
                reset_support=True,
            ),
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
        ),
    ]
