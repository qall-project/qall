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

from typing import Any, Dict, List, Optional

from qall.object import (
    Resource,
    ResourceProfile,
    ResourceAvailability,
    ClassicalResourceConstraints,
    QuantumResourceConstraints,
    QpuModality,
    TaskResourceAssignment,
    TaskDag,
)


def resolve_workflow_resources(
    task_dag: TaskDag,
    profile: ResourceProfile,
    available_resources: List[Resource],
) -> Dict[str, TaskResourceAssignment]:
    """
    Resolves hardware assignments for every TaskNode in a compiled TaskDag.

    Args:
        task_dag: The compiled TaskDag containing IPLD TaskNodes.
        profile: Active user resource profile (.qall.yml or CLI overrides).
        available_resources: Live resource inventory fetched from provider client.

    Returns:
        A mapping of task_hash -> TaskResourceAssignment for the DAG.
    """
    assignments: Dict[str, TaskResourceAssignment] = {}

    for node in task_dag.nodes:
        task_hash = node.hash

        q_constraints = node.resources.quantum
        c_constraints = node.resources.classical

        qpu_res = resolve_task_qpu(q_constraints, profile, available_resources)
        cpu_res = resolve_task_cpu(c_constraints, profile, available_resources)
        gpu_res = resolve_task_gpu(c_constraints, profile, available_resources)

        provider = profile.provider
        if not provider or provider == "*":
            active = qpu_res or cpu_res or gpu_res
            provider = active.provider if active else "local"

        task_name = getattr(node, "name", None) or task_hash[:8]

        assignments[task_hash] = TaskResourceAssignment(
            task_hash=task_hash,
            task_name=task_name,
            provider=provider,
            qpu=qpu_res,
            cpu=cpu_res,
            gpu=gpu_res,
        )

    return assignments


def resolve_task_qpu(
    constraints: QuantumResourceConstraints,
    profile: ResourceProfile,
    available_resources: List[Resource],
) -> Optional[Resource]:
    """
    Matches quantum constraints against available QPU resources.
    """
    if not _has_quantum_requirements(constraints):
        return None

    allowed_names = profile.allowed.qpu
    candidates: List[Resource] = []

    for res in available_resources:
        if not res.qpu:
            continue

        if res.availability in (
            ResourceAvailability.unavailable,
            ResourceAvailability.maintenance,
        ):
            continue

        if "*" not in allowed_names and res.name not in allowed_names:
            continue

        if (
            constraints.min_qubits > 0
            and res.qpu.available_qubits < constraints.min_qubits
        ):
            continue

        if constraints.modality and not _match_modality(
            constraints.modality, res.qpu.modality
        ):
            continue

        candidates.append(res)

    if not candidates:
        raise RuntimeError(
            f"No QPU available satisfying quantum constraints "
            f"(min_qubits={constraints.min_qubits}, modality={constraints.modality}) "
            f"among authorized profile resources: {allowed_names}"
        )

    return _apply_matching_strategy(
        candidates, profile.match_strategy, resource_type="qpu"
    )


def resolve_task_cpu(
    constraints: ClassicalResourceConstraints,
    profile: ResourceProfile,
    available_resources: List[Resource],
) -> Optional[Resource]:
    """
    Matches classical CPU constraints against available CPU resources.
    """
    if not _has_cpu_requirements(constraints):
        return None

    allowed_names = profile.allowed.cpu
    candidates: List[Resource] = []

    for res in available_resources:
        if not res.cpu:
            continue

        if res.availability in (
            ResourceAvailability.unavailable,
            ResourceAvailability.maintenance,
        ):
            continue

        if "*" not in allowed_names and res.name not in allowed_names:
            continue

        if constraints.min_cpu > 0 and res.cpu.available_cores < constraints.min_cpu:
            continue

        if (
            constraints.min_ram_gb > 0
            and res.cpu.available_memory_gb < constraints.min_ram_gb
        ):
            continue

        candidates.append(res)

    if not candidates:
        raise RuntimeError(
            f"No CPU resource satisfying classical constraints "
            f"(min_cpu={constraints.min_cpu}, min_ram_gb={constraints.min_ram_gb}) "
            f"among authorized profile resources: {allowed_names}"
        )

    return _apply_matching_strategy(
        candidates, profile.match_strategy, resource_type="cpu"
    )


def resolve_task_gpu(
    constraints: ClassicalResourceConstraints,
    profile: ResourceProfile,
    available_resources: List[Resource],
) -> Optional[Resource]:
    """
    Matches GPU constraints against available GPU resources.
    """
    if not _has_gpu_requirements(constraints):
        return None

    allowed_names = profile.allowed.gpu
    candidates: List[Resource] = []

    for res in available_resources:
        if not res.gpu:
            continue

        if res.availability in (
            ResourceAvailability.unavailable,
            ResourceAvailability.maintenance,
        ):
            continue

        if "*" not in allowed_names and res.name not in allowed_names:
            continue

        if constraints.min_gpu > 0 and res.gpu.gpu_count < constraints.min_gpu:
            continue

        if (
            constraints.min_vram_gb > 0
            and res.gpu.vram_per_gpu_gb < constraints.min_vram_gb
        ):
            continue

        candidates.append(res)

    if not candidates:
        raise RuntimeError(
            f"No GPU resource satisfying constraints "
            f"(min_gpu={constraints.min_gpu}, min_vram_gb={constraints.min_vram_gb}) "
            f"among authorized profile resources: {allowed_names}"
        )

    return _apply_matching_strategy(
        candidates, profile.match_strategy, resource_type="gpu"
    )


def _has_quantum_requirements(c: QuantumResourceConstraints) -> bool:
    return bool(c and (c.min_qubits > 0 or c.modality is not None))


def _has_cpu_requirements(c: ClassicalResourceConstraints) -> bool:
    return bool(c and (c.min_cpu > 0 or c.min_ram_gb > 0))


def _has_gpu_requirements(c: ClassicalResourceConstraints) -> bool:
    return bool(c and (c.min_gpu > 0 or c.min_vram_gb > 0))


def _match_modality(req_modality: Any, res_modality: Any) -> bool:
    req_str = (
        req_modality.value
        if isinstance(req_modality, QpuModality)
        else str(req_modality)
    )

    res_str = (
        res_modality.value
        if isinstance(res_modality, QpuModality)
        else str(res_modality)
    )

    return req_str.lower() == res_str.lower()


def _apply_matching_strategy(
    candidates: List[Resource], strategy: str, resource_type: str
) -> Resource:
    if strategy == "cheapest":
        if resource_type == "qpu":
            candidates.sort(key=lambda r: r.price.price_per_shot)
        else:
            candidates.sort(key=lambda r: r.price.price_per_hour)
    elif strategy == "performance":
        if resource_type == "qpu":
            candidates.sort(key=lambda r: r.qpu.available_qubits, reverse=True)
        elif resource_type == "cpu":
            candidates.sort(key=lambda r: r.cpu.available_cores, reverse=True)
        elif resource_type == "gpu":
            candidates.sort(
                key=lambda r: r.gpu.gpu_count * r.gpu.vram_per_gpu_gb, reverse=True
            )

    return candidates[0]
