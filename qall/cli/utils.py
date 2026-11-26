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
import ast
import json
import typer

from typing import Any, Optional

from qall.object import Tag, TaskDag, WorkflowPlan, Resource, ResourceAvailability


def pretty_resources(resources: list[Resource]) -> str:
    if not resources:
        return "No resources available."

    qpus = [r for r in resources if r.qpu]
    gpus = [r for r in resources if not r.qpu and r.gpu]
    cpus = [r for r in resources if not r.qpu and not r.gpu and r.cpu]

    sections: list[str] = []

    if qpus:
        sections.append(f"Quantum Resources ({len(qpus)}):")
        for r in qpus:
            q = r.qpu
            status = r.availability.value
            color = (
                typer.colors.GREEN
                if r.availability == ResourceAvailability.available
                else typer.colors.YELLOW
            )
            price_parts = []
            if r.price.price_per_hour:
                price_parts.append(f"{r.price.price_per_hour:g} {r.price.currency}/h")
            if r.price.price_per_shot:
                price_parts.append(
                    f"{r.price.price_per_shot:g} {r.price.currency}/shot"
                )
            if r.price.price_per_circuit:
                price_parts.append(
                    f"{r.price.price_per_circuit:g} {r.price.currency}/circuit"
                )
            pricing = ", ".join(price_parts) if price_parts else "free"
            workers = (
                f" | {len(r.compatible_workers)} worker(s)"
                if r.compatible_workers
                else ""
            )

            sections.append(
                f"  - {typer.style(r.name, bold=True)} [{r.provider}] ({typer.style(status, fg=color)})\n"
                f"      type={q.type.value} | modality={q.modality.value} | tech={q.technology.value} "
                f"| qubits={q.available_qubits} | max_shots={q.max_shots} | price={pricing}{workers}"
            )

    if gpus:
        sections.append(f"GPU Resources ({len(gpus)}):")
        for r in gpus:
            g = r.gpu
            c_info = (
                f" | {r.cpu.available_cores} vCPU, {r.cpu.available_memory_gb} GB RAM"
                if r.cpu
                else ""
            )
            pricing = (
                f"{r.price.price_per_hour:g} {r.price.currency}/h"
                if r.price.price_per_hour
                else "free"
            )
            sections.append(
                f"  - {typer.style(r.name, bold=True)} [{r.provider}] ({r.availability.value})\n"
                f"      {g.gpu_count}x {g.model_name or 'GPU'} ({g.vram_per_gpu_gb} GB VRAM){c_info} | price={pricing}"
            )

    if cpus:
        sections.append(f"CPU Resources ({len(cpus)}):")
        for r in cpus:
            c = r.cpu
            pricing = (
                f"{r.price.price_per_hour:g} {r.price.currency}/h"
                if r.price.price_per_hour
                else "free"
            )
            sections.append(
                f"  - {typer.style(r.name, bold=True)} [{r.provider}] ({r.availability.value})\n"
                f"      {c.available_cores} cores | {c.available_memory_gb} GB RAM | {c.architecture} | price={pricing}"
            )

    return "\n".join(sections)


def pretty_workflow_build(tag: Tag, dag: TaskDag) -> str:
    nodes_by_hash = {node.hash: node for node in dag.nodes}
    payloads_by_hash = {payload.hash: payload for payload in dag.payloads}

    lines = [
        f"Workflow built: {typer.style(str(tag), bold=True)} ({dag.root_hash})",
        f"Tasks ({len(dag.nodes)}):",
    ]

    for node in dag.nodes:
        role = "entrypoint" if node.metadata.entrypoint else "task"
        payload = payloads_by_hash.get(node.payload_hash)
        quantum_runs = payload.metadata.get("quantum_runs", []) if payload else []
        formats = [
            r.get("input_format")
            for r in quantum_runs
            if isinstance(r, dict) and r.get("input_format")
        ]
        kind = f"quantum ({', '.join(formats)})" if formats else "classical"
        children = [
            nodes_by_hash[h].metadata.name if h in nodes_by_hash else h[:12]
            for h in node.children.values()
        ]
        deps = f" -> [{', '.join(children)}]" if children else ""

        lines.append(
            f"  - {typer.style(node.metadata.name, bold=True)} [{role}, {kind}] ({node.hash[:16]}...){deps}"
        )

    return "\n".join(lines)


def pretty_workflow_plan(plan: WorkflowPlan, dag: Optional[TaskDag] = None) -> str:
    nodes_by_hash = {node.hash: node for node in dag.nodes} if dag else {}

    lines = [
        f"Execution plan for {typer.style(str(plan.tag), bold=True)}:",
    ]

    for task_hash, assignment in plan.task_assignments.items():
        node = nodes_by_hash.get(task_hash)
        task_label = (
            f"{node.metadata.name} ({task_hash[:12]}...)" if node else task_hash
        )
        res_summary = (
            ", ".join(
                f"{r.name} ({'QPU' if r.qpu else 'GPU' if r.gpu else 'CPU'})"
                for r in assignment.resources
            )
            or "none"
        )
        worker_info = (
            f" | worker: {assignment.worker_hash[:16]}..."
            if assignment.worker_hash
            else ""
        )

        lines.append(
            f"  - {typer.style(task_label, bold=True)} [{assignment.provider}]: {res_summary}{worker_info}"
        )

    return "\n".join(lines)


def pretty_artifact(artifacts) -> str:
    """Copy-paste ``qall artifact show <hash>`` hints for each generated artifact.

    Each hint lets the user launch the CLI command that deserializes and prints
    the matching local artifact, optionally annotated with the producing task.
    Artifacts without a usable content hash are skipped.
    """
    hints = ["To show an artifact, run the following command(s):"] if artifacts else []
    for artifact in artifacts or []:
        artifact_hash = artifact.hash
        if not artifact_hash:
            continue

        hint = f"\n\t-> 'qall artifact show {artifact_hash}'"
        hints.append(hint)

    return "".join(hints)


def parse_daemon_backend(value: str) -> str:
    """
    Validate and normalize the ``--daemon-backend`` CLI value.
    """
    normalized = (value or "docker").strip().lower()

    if normalized not in ("docker", "systemd"):
        raise typer.BadParameter(
            f"Invalid daemon backend: {normalized} (expected 'docker' or 'systemd')"
        )

    return normalized


def parse_systemd_scope(value: str) -> str:
    """
    Validate and normalize the ``--scope`` CLI value for the systemd backend.
    """
    normalized = (value or "user").strip().lower()

    if normalized not in ("system", "user"):
        raise typer.BadParameter(
            f"Invalid systemd scope: {normalized} (expected 'user' or 'system')"
        )

    return normalized


def _coerce_value(raw: str) -> Any:
    """Convert CLI string tokens to Python literals when possible, else keep str."""
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("none", "null"):
        return None
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        pass
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def parse_extra_args(args: list[str]) -> dict[str, str]:
    """
    Parses arbitrary extra CLI option flags into a clean Python dictionary.
    Handles '--key=value', '--key value', and standalone boolean flags.
    Normalizes keys by removing leading dashes and replacing hyphens with underscores.

    Example:
        ['--project-id=123', '--secret-key', 'abc', '--verbose']
        -> {'project_id': '123', 'secret_key': 'abc', 'verbose': 'true'}
    """
    extra_dict = {}
    i = 0

    while i < len(args):
        arg = args[i]

        if arg.startswith("--"):
            # Clean the prefix and prepare the key
            clean_arg = arg.lstrip("-")

            if "=" in clean_arg:
                # Case A: Syntax option is '--key=value'
                key, val = clean_arg.split("=", 1)
                extra_dict[key.replace("-", "_")] = val
                i += 1
            else:
                # Case B: Syntax option is '--key value' or standalone flag
                key = clean_arg.replace("-", "_")

                # Check if the next argument exists and is a value (not another flag)
                if i + 1 < len(args) and not args[i + 1].startswith("-"):
                    extra_dict[key] = args[i + 1]
                    i += 2
                else:
                    # Fallback flag default value if standalone
                    extra_dict[key] = "true"
                    i += 1
        else:
            # Skip invalid positions or unformatted extra strings
            i += 1

    return extra_dict


def parse_cli_args(raw_args: list[str]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """
    Parses extra CLI tokens into `(args, kwargs)` for a workflow entrypoint.
    Supports positional values, `--key=value`, `--key value` (including negative numbers),
    and standalone boolean `--flag` options, with automatic literal type coercion.
    """
    pos_args: list[Any] = []
    kw_args: dict[str, Any] = {}
    i = 0

    while i < len(raw_args):
        token = raw_args[i]

        if token.startswith("--") and len(token) > 2:
            clean = token[2:]
            if "=" in clean:
                key, val = clean.split("=", 1)
                key = key.replace("-", "_")
                if not key.isidentifier():
                    raise typer.BadParameter(f"Invalid argument name: {key!r}")
                kw_args[key] = _coerce_value(val)
                i += 1
            else:
                key = clean.replace("-", "_")
                if not key.isidentifier():
                    raise typer.BadParameter(f"Invalid argument name: {key!r}")

                # Next token is a value if it exists and is not another '--option'
                # (allows negative numbers like '--offset -5')
                if i + 1 < len(raw_args) and not raw_args[i + 1].startswith("--"):
                    kw_args[key] = _coerce_value(raw_args[i + 1])
                    i += 2
                else:
                    kw_args[key] = True
                    i += 1
        else:
            pos_args.append(_coerce_value(token))
            i += 1

    return tuple(pos_args), kw_args
