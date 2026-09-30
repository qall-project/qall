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
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ClassicalResourceConstraints:
    min_cpu: int = 1
    min_gpu: int = 0
    min_ram_gb: int = 1
    min_bandwidth_mbps: int = 1
    min_vram_gb: int = 0

    def to_dict(self) -> dict:
        return {
            "min_cpu": self.min_cpu,
            "min_gpu": self.min_gpu,
            "min_ram_gb": self.min_ram_gb,
            "min_bandwidth_mbps": self.min_bandwidth_mbps,
            "min_vram_gb": self.min_vram_gb,
        }


@dataclass(frozen=True)
class QuantumResourceConstraints:
    modality: str = None  # "gate_based", "analog", "photonic"
    min_qubits: int = 0

    def to_dict(self) -> dict:
        return {"modality": self.modality, "min_qubits": self.min_qubits}
