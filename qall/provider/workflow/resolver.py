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
from typing import List

from qall.object import Resource, QuantumResourceConstraints, ResourceProfile


def resolve_qpu(
    constraints: QuantumResourceConstraints,
    profile: ResourceProfile,
    available_resources: List[Resource],
) -> Resource:
    allowed_names = profile.allowed.qpu

    candidates = []

    for res in available_resources:
        if not res.qpu:
            continue

        if "*" not in allowed_names and res.name not in allowed_names:
            continue

        if constraints.min_qubits and res.qpu.available_qubits < constraints.min_qubits:
            continue

        if constraints.modality and res.qpu.modality != constraints.modality:
            continue

        candidates.append(res)

    if not candidates:
        raise RuntimeError(
            f"No QPU available satisfies the constraints (min_qubits={constraints.min_qubits}) "
            f"among the authorized resources : {allowed_names}"
        )

    if profile.match_strategy == "cheapest":
        candidates.sort(key=lambda r: r.pricing.price_per_shot)
    elif profile.match_strategy == "performance":
        candidates.sort(key=lambda r: r.qpu.available_qubits, reverse=True)

    return candidates[0]
