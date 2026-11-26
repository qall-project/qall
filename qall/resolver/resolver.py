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

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from qall.interop.mapping import is_circuit_convertible, normalize_circuit_type

from qall.registry import BlockRegistry

from qall.object import (
    Resource,
    ResourceProfile,
    ResourceAvailability,
    TaskResourceAssignment,
    TaskNode,
    TaskPayload,
    TaskDag,
)


@dataclass(frozen=True)
class _WorkerCandidate:
    worker_hash: str
    worker_input_format: str
    conversion_cost: int


def resolve_workflow_resources(
    task_dag: TaskDag,
    profile: ResourceProfile,
    available_resources: List[Resource],
    registry: Optional[BlockRegistry] = None,
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
    registry = registry or BlockRegistry(read_only=True)

    for node in task_dag.nodes:
        task_hash = node.hash
        task_resources = []
        quantum_res: Optional[Resource] = None
        worker_hash: Optional[str] = None

        payload = task_dag.find(node.payload_hash)
        quantum_runs = payload.metadata.get("quantum_runs", []) if payload else []

        if node.is_quantum or bool(quantum_runs):
            quantum_res, worker_hash = resolve_task_quantum(
                node, payload, profile, available_resources, registry
            )
            task_resources.append(quantum_res)

        classical_res = resolve_task_classical(node, profile, available_resources)
        task_resources.append(classical_res)

        provider = profile.provider
        if not provider or provider == "*":
            active = quantum_res or classical_res
            provider = active.provider if active else "local"

        assignments[task_hash] = TaskResourceAssignment(
            task_hash=task_hash,
            provider=provider,
            resources=task_resources,
            worker_hash=worker_hash,
        )

    return assignments


def resolve_task_quantum(
    node: TaskNode,
    payload: TaskPayload,
    profile: ResourceProfile,
    available_resources: List[Resource],
    registry: Optional[BlockRegistry] = None,
) -> tuple[Resource, str]:
    registry = registry or BlockRegistry(read_only=True)
    constraints = node.resources.quantum
    quantum_runs = payload.metadata.get("quantum_runs", []) if payload else []
    client_formats = [
        normalize_circuit_type(quantum_run["input_format"])
        for quantum_run in quantum_runs
        if isinstance(quantum_run, dict) and quantum_run.get("input_format")
    ]

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

        best_worker = _select_best_worker(
            compatible_workers=res.compatible_workers,
            client_formats=client_formats,
            registry=registry,
        )

        if not best_worker:
            continue

        candidates.append((res, best_worker))

    if not candidates:
        raise RuntimeError(
            f"No QPU available satisfying constraints "
            f"(min_qubits={constraints.min_qubits}, min_shots={constraints.min_shots}, "
            f"provider={constraints.qpu_provider}, modality={constraints.qpu_modality}) "
            f"among authorized profile resources: {allowed_names}"
        )

    if profile.match_strategy == "performance":
        candidates.sort(
            key=lambda pair: (-pair[0].qpu.available_qubits, pair[1].conversion_cost)
        )
    else:
        candidates.sort(
            key=lambda pair: (pair[0].price.price_per_shot, pair[1].conversion_cost)
        )

    best_resource, best_worker = candidates[0]
    return best_resource, best_worker.worker_hash


def resolve_task_classical(
    node: TaskNode,
    profile: ResourceProfile,
    available_resources: List[Resource],
) -> Resource:
    constraints = node.resources.classical

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


def _select_best_worker(
    compatible_workers: list[str],
    client_formats: list[str],
    registry: BlockRegistry,
) -> Optional[_WorkerCandidate]:
    eligible: list[_WorkerCandidate] = []

    for worker_hash in compatible_workers or []:
        if not worker_hash:
            continue

        worker_node = registry.get_worker_node_from_local(hash=worker_hash)
        raw_fmt = (worker_node.metadata or {}).get("input_format", "")
        if not raw_fmt:
            continue

        worker_fmt = normalize_circuit_type(raw_fmt)
        if not all(
            is_circuit_convertible(client_fmt, worker_fmt)
            for client_fmt in client_formats
        ):
            continue

        conversion_cost = sum(1 for fmt in client_formats if fmt != worker_fmt)
        eligible.append(
            _WorkerCandidate(
                worker_hash=worker_hash,
                worker_input_format=worker_fmt,
                conversion_cost=conversion_cost,
            )
        )

    if not eligible:
        return None

    return min(eligible, key=lambda w: w.conversion_cost)


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
