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
    ResourceAvailability,
)

from qall.provider.workflow import WorkflowProviderClient, workflow_provider

from scaleway_qaas_client.v1alpha1 import QaaSClient, QaaSPlatform


@workflow_provider("scaleway")
class ScalewayWorkflowProviderClient(WorkflowProviderClient):
    def __init__(self):
        self.__client = None

    def __enter__(self):
        raise NotImplementedError

    def __exit__(self, exc_type, exc_val, exc_tb):
        raise NotImplementedError

    def login(self, credentials: dict) -> bool:
        project_id = credentials.get("project_id")
        secret_key = credentials.get("secret_key")
        url = credentials.get("url", "https://api.scaleway.com/qaas/v1alpha1")

        print(
            f"Logging in with project_id: {project_id}, secret_key: {secret_key}, url: {url}"
        )

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

    def list_resources(self, filters: dict) -> list[Resource]:

        resources: list[Resource] = []

        for p in platforms:
            resource = self._map_platform_to_resource(p)

            if filters:
                if (
                    filters.get("qpu_type")
                    and resource.qpu
                    and resource.qpu.type != filters["qpu_type"]
                ):
                    continue
                if (
                    filters.get("min_qubits")
                    and resource.qpu
                    and resource.qpu.available_qubits < filters["min_qubits"]
                ):
                    continue

            resources.append(resource)

        return resources

    def _map_platform_to_resource(self, p: QaaSPlatform) -> Resource:
        platform_id = self._get_attr(p, "id", "")
        name = self._get_attr(p, "name", platform_id)
        provider_name = self._get_attr(p, "provider_name", "unknown").lower()
        technology_raw = self._get_attr(p, "technology", "unknown").lower()
        type_raw = str(self._get_attr(p, "type", "unknown")).lower()
        status_raw = str(self._get_attr(p, "availability", "unknown")).lower()

        max_qubits = int(self._get_attr(p, "max_qubit_count", 0))
        max_shots = int(self._get_attr(p, "max_shot_count", 0))
        is_bookable = bool(self._get_attr(p, "is_bookable", False))

        price_per_hour = float(self._get_attr(p, "price_per_hour", 0.0) or 0.0)
        price_per_shot = float(self._get_attr(p, "price_per_shot", 0.0) or 0.0)
        price_per_circuit = float(self._get_attr(p, "price_per_circuit", 0.0) or 0.0)

        qpu_type = self._resolve_qpu_type(type_raw, name)
        technology = self._resolve_technology(technology_raw)
        modality = self._resolve_modality(provider_name)
        availability = self._resolve_availability(status_raw)

        qpu_spec = QpuSpec(
            available_qubits=max_qubits,
            max_shots=max_shots,
            modality=modality,
            technology=technology,
            model_name=self._get_attr(p, "title", name),
            type=qpu_type,
            bookable=is_bookable,
        )

        price = ResourcePrice(
            price_per_hour=price_per_hour,
            price_per_shot=price_per_shot,
            price_per_circuit=price_per_circuit,
            price_currency="EUR",
        )

        description = self._get_attr(p, "description", "")

        metadata = {
            "vendor": provider_name,
        }

        return Resource(
            name=name,
            id=platform_id,
            provider="scaleway",
            region="fr-par",
            qpu=qpu_spec,
            price=price,
            availability=availability,
            metadata=metadata,
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
            "quandela": QpuModality.digital,
            "aqt": QpuModality.digital,
            "iqm": QpuModality.digital,
            "quobly": QpuModality.digital,
            "quobly": QpuModality.digital,
            "qperfect": QpuModality.digital,
            "nvidia": QpuModality.digital,
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
