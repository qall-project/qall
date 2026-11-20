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

from qall.provider.workflow import WorkflowProviderClient, workflow_provider


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

    def list_resources(self, filters: Optional[dict] = None) -> list[Resource]:
        self.register_provider_workers("local")
        return [get_local_resource(), *self._build_local_qpu_resources()]

    def _build_local_qpu_resources(self) -> list[Resource]:
        aer_workers = self.compatible_workers(LocalWorker.QISKIT)
        qsim_workers = self.compatible_workers(LocalWorker.CIRQ)
        cudaq_workers = self.compatible_workers(LocalWorker.CUDAQ)
        pulser_workers = self.compatible_workers(LocalWorker.PULSER)
        perceval_workers = self.compatible_workers(LocalWorker.PERCEVAL)


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
                model_name="Qiskit Aer emulator",
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
                gateset=["cz", "rz", "rx", "h", "x", "t", "s"],
                model_name="Cirq QSim emulator",
                type=QpuType.emulator,
                bookable=False,
                mcm_support=True,
                reset_support=True,
            ),
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
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
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
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
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
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
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
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
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
        ),
        Resource(
            id="local-perceval-emulator",
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
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
        ),
        Resource(
            id="local-perceval-emulator",
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
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
        ),
        Resource(
            id="local-perceval-emulator",
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
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
        ),
        Resource(
            id="local-perceval-emulator",
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
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
        ),
        Resource(
            id="local-perceval-emulator",
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
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
        ),
        Resource(
            id="local-perceval-emulator",
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
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
        ),
        Resource(
            id="local-perceval-emulator",
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
            price=ResourcePrice(price_per_shot=0.0, price_per_hour=0.0, currency="EUR"),
        ),
    ]
