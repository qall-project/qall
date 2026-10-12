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

from .local import get_local_resource

from qall.object import (
    Resource,
    ResourceProfile,
    ResourceAvailability,
    ResourcePrice,
    ClassicalResourceConstraints,
    QuantumResourceConstraints,
    TaskResourceAssignment,
    TaskDag,
)


def resolve_workflow_resources(
    task_dag: TaskDag,
    profile: ResourceProfile,
    available_resources: List[Resource],
    replace_to_local: bool = False,
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

        if not replace_to_local:
            cpu_res = resolve_task_cpu(c_constraints, profile, available_resources)
            gpu_res = resolve_task_gpu(c_constraints, profile, available_resources)
        else:
            cpu_res = get_local_resource()
            gpu_res = None

        provider = profile.provider

        if not provider or provider == "*":
            active = qpu_res or cpu_res or gpu_res
            provider = active.provider if active else "local"

        merged_resource = _merge_task_resource(
            qpu_res=qpu_res,
            cpu_res=cpu_res,
            gpu_res=gpu_res,
            provider=provider,
        )

        assignments[task_hash] = TaskResourceAssignment(
            task_hash=task_hash,
            provider=provider,
            resource=merged_resource,
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

        qpu_spec = res.qpu

        if (
            constraints.min_qubits > 0
            and qpu_spec.available_qubits < constraints.min_qubits
        ):
            continue

        if constraints.min_shots > 0 and qpu_spec.max_shots < constraints.min_shots:
            continue

        if constraints.qpu_mcm_support and not qpu_spec.mcm_support:
            continue

        if constraints.qpu_reset_support and not qpu_spec.reset_support:
            continue

        if constraints.qpu_provider and not _compare_str_or_enum(
            constraints.qpu_provider, qpu_spec.provider
        ):
            continue

        if constraints.qpu_modality and not _compare_str_or_enum(
            constraints.qpu_modality, qpu_spec.modality
        ):
            continue

        if constraints.qpu_technology and not _compare_str_or_enum(
            constraints.qpu_technology, qpu_spec.technology
        ):
            continue

        if constraints.qpu_topology and not _compare_str_or_enum(
            constraints.qpu_topology, qpu_spec.topology
        ):
            continue

        if constraints.qpu_gateset:
            required_gates = {g.lower() for g in constraints.qpu_gateset}
            supported_gates = {g.lower() for g in qpu_spec.gateset}
            if not required_gates.issubset(supported_gates):
                continue

        candidates.append(res)

    if len(candidates) == 0:
        raise RuntimeError(
            f"No QPU available satisfying constraints "
            f"(min_qubits={constraints.min_qubits}, min_shots={constraints.min_shots}, "
            f"provider={constraints.qpu_provider}, modality={constraints.qpu_modality}, "
            f"mcm={constraints.qpu_mcm_support}, reset={constraints.qpu_reset_support}) "
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


def _has_quantum_requirements(c: Optional[QuantumResourceConstraints]) -> bool:
    if not c:
        return False

    return any(
        [
            c.min_qubits > 0,
            c.min_shots > 0,
            c.min_ops > 0,
            c.qpu_modality is not None,
            c.qpu_provider is not None,
            c.qpu_technology is not None,
            c.qpu_topology is not None,
            bool(c.qpu_gateset),
            c.qpu_mcm_support,
            c.qpu_reset_support,
        ]
    )


def _has_cpu_requirements(c: ClassicalResourceConstraints) -> bool:
    return bool(c and (c.min_cpu > 0 or c.min_ram_gb > 0))


def _has_gpu_requirements(c: ClassicalResourceConstraints) -> bool:
    return bool(c and (c.min_gpu > 0 or c.min_vram_gb > 0))


def _compare_str_or_enum(val1: Any, val2: Any) -> bool:
    if val1 is None or val2 is None:
        return False

    str1 = val1.value if hasattr(val1, "value") else str(val1)
    str2 = val2.value if hasattr(val2, "value") else str(val2)

    return str1.lower() == str2.lower()


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


def _merge_task_resource(
    qpu_res: Optional[Resource],
    cpu_res: Optional[Resource],
    gpu_res: Optional[Resource],
    provider: str,
) -> Resource:
    """
    Merges resolved QPU, CPU, and GPU candidates into a single unified Resource.
    """
    primary = qpu_res or cpu_res or gpu_res
    resource_name = primary.name if primary else "default-resource"

    # Extract specs from individual resolution results
    qpu_spec = qpu_res.qpu if qpu_res else None
    cpu_spec = cpu_res.cpu if cpu_res else (qpu_res.cpu if qpu_res else None)
    gpu_spec = gpu_res.gpu if gpu_res else (qpu_res.gpu if qpu_res else None)

    # Accumulate price (QPU shot pricing + classical hourly pricing)
    price_per_shot = (
        qpu_res.price.price_per_shot if (qpu_res and qpu_res.price) else 0.0
    )
    price_per_circuit = (
        qpu_res.price.price_per_circuit if (qpu_res and qpu_res.price) else 0.0
    )
    price_per_hour = 0.0

    if cpu_res and cpu_res.price:
        price_per_hour += cpu_res.price.price_per_hour

    if gpu_res and gpu_res.price:
        price_per_hour += gpu_res.price.price_per_hour

    currency = primary.price.currency if (primary and primary.price) else "EUR"

    return Resource(
        name=resource_name,
        provider=provider,
        availability=ResourceAvailability.available,
        qpu=qpu_spec,
        cpu=cpu_spec,
        gpu=gpu_spec,
        price=ResourcePrice(
            price_per_shot=price_per_shot,
            price_per_circuit=price_per_circuit,
            price_per_hour=price_per_hour,
            currency=currency,
        ),
    )
