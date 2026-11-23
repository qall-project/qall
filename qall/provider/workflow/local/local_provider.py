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

from typing import List, Optional

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

from qall.provider.workflow import WorkflowProviderClient, workflow_provider
from qall.provider.qc.local import LocalWorkerType, get_local_worker_catalog


@workflow_provider("local")
class LocalWorkflowProviderClient(WorkflowProviderClient):
    def get_default_config_template(self) -> str:
        return """# Qall Configuration File (.qall.yml)
profiles:
  local-config:
    provider: "local"
    default: True
    match_strategy: "cheapest"

    allowed:
      qpu:
        - "*"
      cpu:
        - "*"
      gpu:
        - "*"
"""

    def get_credential_fields(self) -> list[dict]:
        return []

    def login(self, credentials: Optional[dict] = None) -> bool:
        return True

    def list_classical_resources(self) -> list[Resource]:
        return [
            self._get_local_clasical_resource(),
        ]

    def list_quantum_resources(self) -> list[Resource]:
        return self._get_local_quantum_resources()

    def _get_local_clasical_resource(self) -> Resource:
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

    def _get_local_quantum_resources(self) -> List[Resource]:
        worker_catalog = get_local_worker_catalog()

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
                    model_name="Qiskit Aer emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.AER).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
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
                    gateset=["cz", "rz", "rx", "h", "x", "t", "s"],
                    model_name="Cirq QSim emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.QSIM).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
            ),
            Resource(
                id="local-cudaq-emulator",
                name="LOCAL-CUDAQ",
                provider="local",
                availability=ResourceAvailability.available,
                qpu=QpuSpec(
                    available_qubits=32,
                    max_shots=100000,
                    modality=QpuModality.gate_based,
                    topology=QpuTopology.all_to_all,
                    technology=QpuTechnology.unknown,
                    gateset=["cz", "rz", "rx", "h", "x", "t", "s"],
                    model_name="CUDA-Q runtime emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.CUDAQ).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
            ),
            Resource(
                id="local-pulser-analog-emulator",
                name="LOCAL-PULSER-ANALOG",
                provider="local",
                availability=ResourceAvailability.available,
                qpu=QpuSpec(
                    available_qubits=32,
                    max_shots=2000,
                    modality=QpuModality.analog,
                    topology=QpuTopology.grid,
                    technology=QpuTechnology.unknown,
                    model_name="Pulser emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.PULSER).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
            ),
            Resource(
                id="local-pulser-mock-emulator",
                name="LOCAL-PULSER-MOCK",
                provider="local",
                availability=ResourceAvailability.available,
                qpu=QpuSpec(
                    available_qubits=32,
                    max_shots=2000,
                    modality=QpuModality.analog,
                    topology=QpuTopology.grid,
                    technology=QpuTechnology.unknown,
                    model_name="Pulser emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.PULSER).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
            ),
            Resource(
                id="local-pulser-digital-analog-emulator",
                name="LOCAL-PULSER-DIGITAL-ANALOG",
                provider="local",
                availability=ResourceAvailability.available,
                qpu=QpuSpec(
                    available_qubits=32,
                    max_shots=2000,
                    modality=QpuModality.analog,
                    topology=QpuTopology.grid,
                    technology=QpuTechnology.unknown,
                    model_name="Pulser emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.PULSER).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
            ),
            Resource(
                id="local-perceval-emulator-slos",
                name="LOCAL-PERCEVAL-SLOS",
                provider="local",
                availability=ResourceAvailability.available,
                qpu=QpuSpec(
                    available_qubits=32,
                    max_shots=100000,
                    modality=QpuModality.linear_optic,
                    topology=QpuTopology.all_to_all,
                    technology=QpuTechnology.discrete_photon,
                    model_name="Perceval emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.PERCEVAL).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
            ),
            Resource(
                id="local-perceval-emulator-mps",
                name="LOCAL-PERCEVAL-MPS",
                provider="local",
                availability=ResourceAvailability.available,
                qpu=QpuSpec(
                    available_qubits=32,
                    max_shots=100000,
                    modality=QpuModality.linear_optic,
                    topology=QpuTopology.all_to_all,
                    technology=QpuTechnology.discrete_photon,
                    model_name="Perceval emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.PERCEVAL).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
            ),
            Resource(
                id="local-perceval-emulator-naive",
                name="LOCAL-PERCEVAL-NAIVE",
                provider="local",
                availability=ResourceAvailability.available,
                qpu=QpuSpec(
                    available_qubits=32,
                    max_shots=100000,
                    modality=QpuModality.linear_optic,
                    topology=QpuTopology.all_to_all,
                    technology=QpuTechnology.discrete_photon,
                    model_name="Perceval emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.PERCEVAL).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
            ),
            Resource(
                id="local-perceval-emulator-naive-approx",
                name="LOCAL-PERCEVAL-NAIVE-APPROX",
                provider="local",
                availability=ResourceAvailability.available,
                qpu=QpuSpec(
                    available_qubits=32,
                    max_shots=100000,
                    modality=QpuModality.linear_optic,
                    topology=QpuTopology.all_to_all,
                    technology=QpuTechnology.discrete_photon,
                    model_name="Perceval emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.PERCEVAL).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
            ),
            Resource(
                id="local-perceval-emulator-slap",
                name="LOCAL-PERCEVAL-SLAP",
                provider="local",
                availability=ResourceAvailability.available,
                qpu=QpuSpec(
                    available_qubits=32,
                    max_shots=100000,
                    modality=QpuModality.linear_optic,
                    topology=QpuTopology.all_to_all,
                    technology=QpuTechnology.discrete_photon,
                    model_name="Perceval emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.PERCEVAL).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
            ),
            Resource(
                id="local-perceval-emulator-sampling",
                name="LOCAL-PERCEVAL-SAMPLING",
                provider="local",
                availability=ResourceAvailability.available,
                qpu=QpuSpec(
                    available_qubits=32,
                    max_shots=100000,
                    modality=QpuModality.linear_optic,
                    topology=QpuTopology.all_to_all,
                    technology=QpuTechnology.discrete_photon,
                    model_name="Perceval emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.PERCEVAL).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
            ),
            Resource(
                id="local-perceval-emulator-clifford",
                name="LOCAL-PERCEVAL-CLIFFORD",
                provider="local",
                availability=ResourceAvailability.available,
                qpu=QpuSpec(
                    available_qubits=32,
                    max_shots=100000,
                    modality=QpuModality.linear_optic,
                    topology=QpuTopology.all_to_all,
                    technology=QpuTechnology.discrete_photon,
                    model_name="Perceval emulator",
                    type=QpuType.emulator,
                    bookable=False,
                    mcm_support=True,
                    reset_support=True,
                ),
                compatible_workers=[
                    worker_catalog.get_by_name(LocalWorkerType.PERCEVAL).hash
                ],
                price=ResourcePrice(
                    price_per_shot=0.0, price_per_hour=0.0, currency="EUR"
                ),
            ),
        ]
