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

from .local import get_local_resource, get_local_qpu_resources

from qall.object import (
    Resource,
    ResourceProfile,
    ResourceAvailability,
    ResourcePrice,
    ClassicalResourceConstraints,
    QuantumResourceConstraints,
    TaskResourceAssignment,
    TaskDag,
    QpuHosting,
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

    is_local_provider = profile.provider == "local"

    qpu_pool = get_local_qpu_resources() if is_local_provider else available_resources

    for node in task_dag.nodes:
        task_hash = node.hash

        q_constraints = node.resources.quantum
        c_constraints = node.resources.classical

        quantum_res = resolve_task_quantum(q_constraints, profile, qpu_pool)

        is_on_premise = (
            quantum_res is not None
            and quantum_res.qpu is not None
            and quantum_res.qpu.hosting == QpuHosting.on_premise
        )

        if is_on_premise and not replace_to_local:
            classical_res = None
        elif replace_to_local or is_local_provider:
            classical_res = get_local_resource()
        else:
            classical_res = resolve_task_classical(
                c_constraints, profile, available_resources
            )

        provider = profile.provider
        if not provider or provider == "*":
            active = quantum_res or classical_res
            provider = active.provider if active else "local"

        merged_resource = _merge_task_resource(
            classical_res=classical_res,
            quantum_res=quantum_res,
            provider=provider,
        )

        assignments[task_hash] = TaskResourceAssignment(
            task_hash=task_hash,
            provider=provider,
            resource=merged_resource,
        )

    return assignments


def resolve_task_quantum(
    constraints: Optional[QuantumResourceConstraints],
    profile: ResourceProfile,
    available_resources: List[Resource],
) -> Optional[Resource]:
    """Valide et résout les contraintes quantiques vers un QPU éligible."""
    if not constraints or not any(
        [
            constraints.min_qubits > 0,
            constraints.min_shots > 0,
            constraints.min_ops > 0,
            constraints.qpu_modality is not None,
            constraints.qpu_provider is not None,
            constraints.qpu_technology is not None,
            constraints.qpu_topology is not None,
            constraints.qpu_gateset is not None and len(constraints.qpu_gateset) > 0,
            constraints.qpu_mcm_support,
            constraints.qpu_reset_support,
        ]
    ):
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

    if not candidates:
        raise RuntimeError(
            f"No QPU available satisfying constraints "
            f"(min_qubits={constraints.min_qubits}, min_shots={constraints.min_shots}, "
            f"provider={constraints.qpu_provider}, modality={constraints.qpu_modality}) "
            f"among authorized profile resources: {allowed_names}"
        )

    return _apply_matching_strategy(
        candidates, profile.match_strategy, resource_type="qpu"
    )


def resolve_task_classical(
    constraints: Optional[ClassicalResourceConstraints],
    profile: ResourceProfile,
    available_resources: List[Resource],
) -> Resource:
    min_cpu = constraints.min_cpu if constraints else 0
    min_ram_gb = constraints.min_ram_gb if constraints else 0
    min_gpu = constraints.min_gpu if constraints else 0
    min_vram_gb = constraints.min_vram_gb if constraints else 0

    needs_gpu = (min_gpu > 0) or (min_vram_gb > 0)
    allowed_names = profile.allowed.gpu if needs_gpu else profile.allowed.cpu
    candidates: List[Resource] = []

    for res in available_resources:
        if res.availability in (
            ResourceAvailability.unavailable,
            ResourceAvailability.maintenance,
        ):
            continue

        if "*" not in allowed_names and res.name not in allowed_names:
            continue

        if res.qpu is not None:
            continue

        if needs_gpu:
            if not res.gpu or res.gpu.gpu_count <= 0:
                continue
            if min_gpu > 0 and res.gpu.gpu_count < min_gpu:
                continue
            if min_vram_gb > 0 and res.gpu.vram_per_gpu_gb < min_vram_gb:
                continue

            if not res.cpu:
                continue
            if min_cpu > 0 and res.cpu.available_cores < min_cpu:
                continue
            if min_ram_gb > 0 and res.cpu.available_memory_gb < min_ram_gb:
                continue
        else:
            if not res.cpu:
                continue
            if res.gpu is not None and res.gpu.gpu_count > 0:
                continue
            if min_cpu > 0 and res.cpu.available_cores < min_cpu:
                continue
            if min_ram_gb > 0 and res.cpu.available_memory_gb < min_ram_gb:
                continue

        candidates.append(res)

    if not candidates:
        if needs_gpu:
            raise RuntimeError(
                f"No GPU resource satisfying classical constraints "
                f"(min_gpu={min_gpu}, min_vram_gb={min_vram_gb}, min_cpu={min_cpu}, min_ram_gb={min_ram_gb}) "
                f"among authorized profile resources: {allowed_names}"
            )
        else:
            raise RuntimeError(
                f"No CPU resource satisfying classical constraints "
                f"(min_cpu={min_cpu}, min_ram_gb={min_ram_gb}) "
                f"among authorized profile resources: {allowed_names}"
            )

    resource_type = "gpu" if needs_gpu else "cpu"
    return _apply_matching_strategy(
        candidates, profile.match_strategy, resource_type=resource_type
    )


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
    quantum_res: Optional[Resource] = None,
    classical_res: Optional[Resource] = None,
    provider: str = "local",
) -> Resource:
    if (
        quantum_res
        and quantum_res.qpu
        and quantum_res.qpu.hosting == QpuHosting.on_premise
    ):
        return Resource(
            id=quantum_res.id,
            name=quantum_res.name,
            provider=provider or quantum_res.provider,
            availability=quantum_res.availability,
            qpu=quantum_res.qpu,
            cpu=quantum_res.cpu,
            gpu=quantum_res.gpu,
            price=quantum_res.price if quantum_res.price else ResourcePrice(),
            metadata=dict(quantum_res.metadata) if quantum_res.metadata else {},
            description=quantum_res.description,
            region=quantum_res.region,
        )

    primary = quantum_res or classical_res
    if not primary:
        raise RuntimeError("quantum resource or classical resource must be not None")

    resource_name = primary.name
    resource_id = primary.id

    qpu_spec = quantum_res.qpu if quantum_res else None

    cpu_spec = (
        classical_res.cpu
        if classical_res
        else (quantum_res.cpu if quantum_res else None)
    )
    gpu_spec = (
        classical_res.gpu
        if classical_res
        else (quantum_res.gpu if quantum_res else None)
    )

    price_per_shot = (
        quantum_res.price.price_per_shot if (quantum_res and quantum_res.price) else 0.0
    )
    price_per_circuit = (
        quantum_res.price.price_per_circuit
        if (quantum_res and quantum_res.price)
        else 0.0
    )
    price_per_hour = 0.0

    if classical_res and classical_res.price:
        price_per_hour += classical_res.price.price_per_hour
    if quantum_res and quantum_res.price:
        price_per_hour += quantum_res.price.price_per_hour

    currency = (
        primary.price.currency
        if (primary and primary.price and primary.price.currency)
        else "EUR"
    )

    return Resource(
        id=resource_id,
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
        metadata=dict(primary.metadata) if primary.metadata else {},
        description=primary.description,
        region=primary.region,
    )
