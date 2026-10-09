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

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class QpuTopology(Enum):
    unknown = "unknown"
    linear = "linear"
    grid = "grid"
    hexagonal = "hexagonal"
    all_to_all = "all_to_all"


class QpuType(Enum):
    unknown = "unknown"
    emulator = "emulator"
    physical = "physical"


class QpuTechnology(Enum):
    unknown = "unknown"
    continuous_photon = "continuous_photon"
    discrete_photon = "discrete_photon"
    superconducting = "superconducting"
    trapped_ion = "trapped_ion"
    neutral_atom = "neutral_atom"
    nv_diamond = "nv_diamond"


class QpuModality(Enum):
    unknown = "unknown"
    digital = "digital"
    analog = "analog"
    digital_analog = "digital_analog"
    annealing = "annealing"


class ResourceAvailability(Enum):
    unknown = "unknown"
    available = "available"
    unavailable = "unavailable"
    maintenance = "maintenance"
    scarce = "scarce"


@dataclass(frozen=True)
class GpuSpec:
    gpu_count: int = 1
    vram_per_gpu_gb: int = 0
    model_name: str = ""
    network_topology: Optional[str] = None


@dataclass(frozen=True)
class CpuSpec:
    available_cores: int = 1
    available_memory_gb: int = 1
    network_bandwidth_mbps: int = 1000
    architecture: str = "x86_64"
    instruction_set: Optional[str] = None
    model_name: str = ""


@dataclass(frozen=True)
class QpuSpec:
    available_qubits: int
    max_shots: int = 10000
    modality: QpuModality = QpuModality.unknown
    topology: QpuTopology = QpuTopology.unknown
    technology: QpuTechnology = QpuTechnology.unknown
    native_gate_set: list[str] = field(default_factory=list)
    model_name: str = ""
    type: QpuType = QpuType.unknown
    bookable: bool = False


@dataclass(frozen=True)
class ResourcePrice:
    price_per_hour: float = 0.0
    price_per_shot: float = 0.0
    price_per_circuit: float = 0.0
    price_currency: str = "EUR"


@dataclass(frozen=True)
class Resource:
    name: str
    provider: str
    id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    description: Optional[str] = ""
    region: Optional[str] = ""
    gpu: Optional[GpuSpec] = None
    cpu: Optional[CpuSpec] = None
    qpu: Optional[QpuSpec] = None
    price: ResourcePrice = field(default_factory=ResourcePrice)
    availability: ResourceAvailability = ResourceAvailability.unknown


@dataclass(frozen=True)
class TaskResourceAssignment:
    """
    Resolved hardware assignment mapped directly to a unique IPLD task_hash.
    """

    task_hash: str
    provider: str
    qpu: Optional[Resource] = None
    cpu: Optional[Resource] = None
    gpu: Optional[Resource] = None

    @property
    def qpu_name(self) -> Optional[str]:
        return self.qpu.name if self.qpu else None

    @property
    def cpu_name(self) -> Optional[str]:
        return self.cpu.name if self.cpu else None

    @property
    def gpu_name(self) -> Optional[str]:
        return self.gpu.name if self.gpu else None

    def to_execution_context(self) -> dict[str, str]:
        context = {"provider": self.provider}
        if self.qpu_name:
            context["target_qpu"] = self.qpu_name
        if self.cpu_name:
            context["target_cpu"] = self.cpu_name
        if self.gpu_name:
            context["target_gpu"] = self.gpu_name
        return context
