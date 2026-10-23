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
from typing import Any, Optional

from qall.object import (
    Workflow,
    Tag,
    WorkflowRun,
    TaskRun,
    Artifact,
    Checkpoint,
    Resource,
    ResourceProfile,
    Log,
    Resource,
    QpuSpec,
    ResourcePrice,
    QpuType,
    QpuTechnology,
    QpuModality,
    QpuTopology,
    QpuHosting,
    ResourceAvailability,
)

from qall.provider.workflow import WorkflowProviderClient, workflow_provider
from qall.provider.login import get_credentials_from_env


from scaleway_qaas_client.v1alpha1 import QaaSClient, QaaSPlatform


@workflow_provider("scaleway")
class ScalewayWorkflowProviderClient(WorkflowProviderClient):
    def __init__(self):
        self.__client = None

    def __enter__(self):
        raise NotImplementedError

    def __exit__(self, exc_type, exc_val, exc_tb):
        raise NotImplementedError

    def get_default_config_template(self) -> str:
        """
        Returns the default YAML configuration template for this provider.
        """
        return f"""# Qall Configuration File (.qall.yml)
profiles:
  scaleway-config:
    provider: "scaleway"
    default: True
    match_strategy: "cheapest" # Resolution strategy: "cheapest" or "performance"

    allowed:
      qpu:
        - "*" # Allow all QPUs, or restrict to specific names (e.g., "QPU-EMERALD-54PQ")
      cpu:
        - "*" # Allow all classical CPU instances
      gpu:
        - "*" # Allow all GPU instances
"""

    def get_credential_fields(self) -> list[dict]:
        return [
            {
                "name": "project_id",
                "prompt": "Scaleway Project ID",
                "hide_input": False,
            },
            {
                "name": "secret_key",
                "prompt": "Scaleway Secret Key",
                "hide_input": True,
            },
        ]

    def login(self, credentials: Optional[dict] = None) -> bool:
        if credentials is None:
            credentials = get_credentials_from_env()

        project_id = credentials.get("project_id")
        secret_key = credentials.get("secret_key")
        url = credentials.get("url", "https://api.scaleway.com")

        self.__client = QaaSClient(
            project_id=project_id,
            secret_key=secret_key,
            url=url,
        )

        platforms = self.__client.list_platforms()

        return platforms is not None and len(platforms) > 0

    def create_workflow(
        tag: Tag,
        registry: str,
        profile: ResourceProfile,
    ) -> Workflow:
        raise NotImplementedError

    def get_workflow(self, workflow_id: str) -> Workflow:
        raise NotImplementedError

    def list_workflows(
        self,
    ) -> list[Workflow]:
        raise NotImplementedError

    def delete_workflow(self, workflow_id: str) -> bool:
        raise NotImplementedError

    def create_workflow_run(self, workflow: Workflow, **kwargs) -> WorkflowRun:
        raise NotImplementedError

    def get_workflow_run(self, workflow_run_id: str) -> WorkflowRun:
        raise NotImplementedError

    def list_workflow_runs(self, workflow_id: str) -> list[WorkflowRun]:
        raise NotImplementedError

    def stop_workflow_run(self, workflow_run_id: str) -> WorkflowRun:
        raise NotImplementedError

    def get_artifact(self, artifact_id: str) -> Artifact:
        raise NotImplementedError

    def download_artifact(self, artifact: Artifact) -> str:
        raise NotImplementedError

    def list_artifacts(self, workflow_run_id: str) -> list[Artifact]:
        raise NotImplementedError

    def get_task_run(self, task_run_id: str) -> TaskRun:
        raise NotImplementedError

    def list_task_runs(self, workflow_run_id: str) -> list[TaskRun]:
        raise NotImplementedError

    def stop_task_run(self, task_run_id: str) -> TaskRun:
        raise NotImplementedError

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        raise NotImplementedError

    def list_checkpoints(self, workflow_run_id: str) -> list[Checkpoint]:
        raise NotImplementedError

    def list_logs(self, workflow_run_id: str) -> list[Log]:
        raise NotImplementedError

    def list_resources(self, filters: Optional[dict] = None) -> list[Resource]:
        platforms = self.__client.list_platforms()
        resources: list[Resource] = []

        for p in platforms:
            resource = self._map_platform_to_resource(p)

            resources.append(resource)

        return resources

    def _map_platform_to_resource(self, p: QaaSPlatform) -> Resource:
        platform_id = p.id
        name = p.name
        provider_name = p.provider_name.lower()
        technology_raw = str(p.technology).lower()
        type_raw = str(p.type_).lower()
        status_raw = str(p.availability).lower()

        max_qubits = p.max_qubit_count
        max_shots = p.max_shot_count
        is_bookable = p.is_bookable

        price_per_hour, _ = self._parse_grpc_money(p.price_per_hour)
        price_per_shot = self._parse_grpc_money(p.price_per_shot)
        price_per_circuit = self._parse_grpc_money(p.price_per_circuit)

        qpu_type = self._resolve_qpu_type(type_raw)
        technology = self._resolve_technology(technology_raw)
        modality = self._resolve_modality(provider_name)
        availability = self._resolve_availability(status_raw)

        qpu_spec = QpuSpec(
            available_qubits=max_qubits,
            max_shots=max_shots,
            topology=QpuTopology.unknown,
            hosting=QpuHosting.remote,
            max_ops=9999,
            modality=modality,
            technology=technology,
            model_name=name,
            type=qpu_type,
            bookable=is_bookable,
            provider=provider_name,
            mcm_support=False,
            reset_support=False,
        )

        price = ResourcePrice(
            price_per_hour=price_per_hour,
            price_per_shot=price_per_shot,
            price_per_circuit=price_per_circuit,
            currency="EUR",
        )

        description = self._get_attr(p, "description", "")

        return Resource(
            name=name,
            id=platform_id,
            provider="scaleway",
            region="fr-par",
            qpu=qpu_spec,
            price=price,
            availability=availability,
            description=description,
        )

    @staticmethod
    def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @staticmethod
    def _resolve_qpu_type(type_str: str) -> QpuType:
        if type_str == "qpu":
            return QpuType.physical
        return QpuType.emulator

    @staticmethod
    def _resolve_technology(tech_str: str) -> QpuTechnology:
        tech_map = {
            "superconducting": QpuTechnology.superconducting,
            "photonic": QpuTechnology.discrete_photon,
            "trapped_ion": QpuTechnology.trapped_ion,
            "neutral_atom": QpuTechnology.neutral_atom,
        }

        return tech_map.get(tech_str.lower(), QpuTechnology.unknown)

    @staticmethod
    def _resolve_modality(provider_name: str) -> QpuModality:
        provider_map = {
            "pasqal": QpuModality.analog,
            "quandela": QpuModality.linear_optic,
            "aqt": QpuModality.gate_based,
            "iqm": QpuModality.gate_based,
            "quobly": QpuModality.gate_based,
            "qiskit": QpuModality.gate_based,
            "quantumlib": QpuModality.gate_based,
            "qperfect": QpuModality.gate_based,
            "nvidia": QpuModality.gate_based,
        }

        return provider_map.get(provider_name.lower(), QpuModality.unknown)

    @staticmethod
    def _resolve_topology(top_str: str) -> QpuTopology:
        return QpuTopology.unknown

    @staticmethod
    def _resolve_availability(status_str: str) -> ResourceAvailability:
        availability_map = {
            "available": ResourceAvailability.available,
            "shortage": ResourceAvailability.unavailable,
            "maintenance": ResourceAvailability.maintenance,
            "scarce": ResourceAvailability.scarce,
        }

        return availability_map.get(status_str.lower(), ResourceAvailability.unknown)

    @staticmethod
    def _parse_grpc_money(money_obj: Any) -> tuple[float, str]:
        """
        Converts a gRPC Money object (units + nanos) into a float price and currency string.
        """
        if not money_obj:
            return 0.0, "EUR"

        if isinstance(money_obj, dict):
            units = money_obj.get("units") or 0
            nanos = money_obj.get("nanos") or 0
            currency = money_obj.get("currency_code") or "EUR"
        else:
            units = getattr(money_obj, "units", 0) or 0
            nanos = getattr(money_obj, "nanos", 0) or 0
            currency = getattr(money_obj, "currency_code", "EUR") or "EUR"

        price = float(units) + (float(nanos) / 1e9)
        return price, currency
