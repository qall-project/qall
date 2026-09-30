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
import importlib
import inspect
import json
import logging
import os
import sys
from collections import deque
from pathlib import Path

import rustworkx as rx
from rustworkx import DAGWouldCycle
from typing import Any, Literal

from .imports import discover_external_imports, lenient_imports
from .task import DECORATORS, TaskSpec

logger = logging.getLogger(__name__)


def _load_pyan():
    """Lazily import pyan3, raising a clear error instead of exiting the process."""
    try:
        from pyan.analyzer import CallGraphVisitor

        return CallGraphVisitor
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "pyan3 is required to build qall workflow call graphs. "
            "Install it with: pip install pyan3"
        ) from exc


def _extract_decorators_from_file(filepath: Path) -> dict[str, list[str]]:
    """
    Parses the target Python file using AST to statically extract decorators.
    Returns a dictionary mapping function names to a list of their decorators.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)
    decorators_map = {}

    for node in ast.walk(tree):
        # Target standard functions and async functions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decs = []
            for dec in node.decorator_list:
                # Use unparse for Python 3.9+ to get the exact decorator string
                # (e.g., '@app.route("/home")')
                if hasattr(ast, "unparse"):
                    decs.append(f"@{ast.unparse(dec)}")
                else:
                    # Fallback for older Python versions
                    if isinstance(dec, ast.Name):
                        decs.append(f"@{dec.id}")
                    elif isinstance(dec, ast.Call) and hasattr(dec.func, "id"):
                        decs.append(f"@{dec.func.id}")
                    else:
                        decs.append("@<complex_decorator>")

            decorators_map[node.name] = decs

    return decorators_map


def _build_call_graph(filepaths: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    """
    Uses pyan3 to generate the nodes and edges of the static call graph for the given files.
    Returns a list of node names and a list of edge dictionaries.
    """
    CallGraphVisitor = _load_pyan()

    # Runs pyan3
    visitor = CallGraphVisitor(filepaths)

    # Process the files to populate the visitor dictionaries
    if hasattr(visitor, "process"):
        visitor.process()

    nodes_set = set()
    edges_list = []

    # Extract nodes (definitions) from defines_edges
    if hasattr(visitor, "defines_edges"):
        for scope_node, defined_nodes in visitor.defines_edges.items():
            for node in defined_nodes:
                name = node.name if hasattr(node, "name") else str(node)
                nodes_set.add(name)

    # Extract edges (uses/calls) from uses_edges
    if hasattr(visitor, "uses_edges"):
        for src_node, tgt_nodes in visitor.uses_edges.items():
            src_name = src_node.name if hasattr(src_node, "name") else str(src_node)

            # Ensure the source node is tracked even if it wasn't in defines_edges
            nodes_set.add(src_name)

            for tgt_node in tgt_nodes:
                tgt_name = tgt_node.name if hasattr(tgt_node, "name") else str(tgt_node)

                # Avoid empty names and add the edge
                if src_name and tgt_name:
                    edges_list.append({"caller": src_name, "callee": tgt_name})

                    # Add callee to nodes_set to capture external/builtin calls
                    nodes_set.add(tgt_name)

    return list(nodes_set), edges_list


def _is_task_decorator(dec_str: str) -> bool:
    clean_dec = dec_str.lstrip("@").split("(")[0].strip()
    parts = clean_dec.split(".")
    return parts[-1] in ("task", "workflow")


def _filter_tasks_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered_nodes = []
    for node in nodes:
        node_decorators: list[str] = node.get("decorators", [])
        if any(_is_task_decorator(d) for d in node_decorators):
            node_name = node.get("name")
            if node_name in TaskSpec._parent_workflow.tasks:
                task = TaskSpec._parent_workflow.tasks[node_name]
                if task not in [n["task"] for n in filtered_nodes]:
                    node["task"] = task
                    filtered_nodes.append(node)
            else:
                raise SyntaxWarning(
                    f"Function {node_name} is not registered as a qall task, did you define another @task or @workflow decorator in your code?"
                )
    return filtered_nodes


def _filter_tasks_edges(
    nodes: list[dict[str, Any]], edges: list[dict[str, str]]
) -> list[dict[str, str]]:
    """
    Filters every edge that is not between two valid task nodes.

    Tasks connected through chains of non-task intermediate functions are
    bridged directly using a transitive closure (BFS) over the static call
    graph, handling deep chains, multiple callers and shared intermediates.

    :param nodes: List of nodes
    :param edges: List of edges
    :return: Filtered list of edges
    """
    valid_nodes_names = {node["name"] for node in nodes}

    # caller -> callees adjacency
    adjacency: dict[str, set[str]] = {}
    # Short name -> source of each task, used to prune import-only edges below.
    task_sources: dict[str, str] = {node["name"]: node["task"].source for node in nodes}
    for edge in edges:
        caller, callee = edge["caller"], edge["callee"]

        # pyan3 records module-level imports as "uses", producing spurious edges
        # between two tasks (e.g. `from other import remote` yields `main -> remote`
        # even when `main` never calls `remote`). If the caller task never mentions
        # the callee by name in its own source, the edge is an import, not a call.
        # Non-task callers are left untouched so BFS bridging still works.
        if caller in task_sources and callee in valid_nodes_names:
            if callee not in task_sources[caller]:
                continue

        adjacency.setdefault(caller, set()).add(callee)

    filtered_edges: set[tuple[str, str]] = set()
    for node in nodes:
        source = node["name"]

        queue = deque([source])
        seen = {source}

        while queue:
            current = queue.popleft()
            for target in adjacency.get(current, ()):
                if target in seen:
                    continue
                seen.add(target)

                if target in valid_nodes_names:
                    # Task boundary: record the edge and do not traverse through
                    # the callee task (that task owns its own outgoing edges).
                    filtered_edges.add((source, target))
                else:
                    # Non-task intermediate: keep traversing to find real tasks.
                    queue.append(target)

    return [
        {"caller": caller, "callee": callee}
        for caller, callee in sorted(filtered_edges)
    ]


def _to_rxgraph(result: dict) -> rx.PyDiGraph:
    graph = rx.PyDiGraph(check_cycle=True)
    nodes = result["nodes"]
    edges = result["edges"]

    id_node_map: dict[str, id] = {}
    for node in nodes:
        node_id = graph.add_node(node["task"].name)
        id_node_map[node["name"]] = node_id

    try:
        for edge in edges:
            parent_id = id_node_map.get(edge["caller"])
            child_id = id_node_map.get(edge["callee"])
            if parent_id is None or child_id is None:
                continue
            graph.add_edge(parent_id, child_id, edge)
    except DAGWouldCycle as e:
        raise ValueError(f"Error: The call graph would create a cycle: {e}") from e

    return graph


def _compile_tasks(filepath: Path):
    """Dynamically loads the target Python file in Task 'COMPILATION' mode."""
    TaskSpec.compilation()

    # STATE COUPLING BRIDGE: Sync variables to any external duplicated TaskSpec classes
    for mod_name, mod in list(sys.modules.items()):
        if (
            "qall" in mod_name
            or mod_name.endswith(".task")
            or mod_name.endswith(".specification")
        ):
            if hasattr(mod, "TaskSpec"):
                target_cls = getattr(mod, "TaskSpec")
                target_cls._parent_workflow = TaskSpec._parent_workflow
                target_cls._mode = TaskSpec._mode
                target_cls._discovered_requirements = TaskSpec._discovered_requirements

    module_name = filepath.stem
    safe_module_name = f"qall.plugins.{module_name}"

    # Resolve the absolute path to the directory containing the workflow file
    parent_dir = str(filepath.parent.resolve())

    # Statically discover the project's third-party imports so missing packages
    # do not crash compilation: they are stubbed during execution below and
    # merged into each task's piprequirements.
    discovered = discover_external_imports(parent_dir)
    TaskSpec._discovered_requirements = discovered

    # Temporarily add the parent directory to Python's path so sibling imports work
    sys.path.insert(0, parent_dir)

    try:
        spec = importlib.util.spec_from_file_location(module_name, str(filepath))
        if spec is None or spec.loader is None:
            print(f"Error: Could not load module spec from {filepath}", file=sys.stderr)
            return

        module = importlib.util.module_from_spec(spec)
        sys.modules[safe_module_name] = module
        with lenient_imports(discovered):
            spec.loader.exec_module(module)
    finally:
        TaskSpec.execution()
        TaskSpec._discovered_requirements = None
        for mod_name, mod in list(sys.modules.items()):
            if (
                "qall" in mod_name
                or mod_name.endswith(".task")
                or mod_name.endswith(".specification")
            ):
                if hasattr(mod, "TaskSpec"):
                    target_cls = getattr(mod, "TaskSpec")
                    target_cls._mode = TaskSpec._mode
                    target_cls._discovered_requirements = (
                        TaskSpec._discovered_requirements
                    )

        if safe_module_name in sys.modules.keys():
            sys.modules.pop(safe_module_name)

        # Clean up sys.path to avoid polluting the global state for subsequent runs
        if parent_dir in sys.path:
            sys.path.remove(parent_dir)


def _module_lives_under(module, directory: Path) -> bool:
    """True if a module physically lives inside `directory` (file or namespace)."""
    file = getattr(module, "__file__", None)
    if file:
        try:
            return Path(file).resolve().is_relative_to(directory)
        except (ValueError, OSError):
            return False

    for path in getattr(module, "__path__", ()) or ():
        try:
            if Path(path).resolve().is_relative_to(directory):
                return True
        except (ValueError, OSError):
            continue
    return False


def _purge_compiled_modules(before: set[str], project_dir: Path) -> None:
    """
    Removes modules that were loaded during a workflow compilation and that live
    under the workflow's directory. Without this, local sibling packages (e.g.
    `utils`, `services`) stay cached in sys.modules and silently corrupt later
    compilations of unrelated workflows that reuse the same names.
    """
    for name, module in list(sys.modules.items()):
        if name in before:
            continue
        if name.startswith("qall.plugins."):
            del sys.modules[name]
        elif _module_lives_under(module, project_dir):
            del sys.modules[name]


def generate_call_graph(filepath: Path, format: Literal["text", "json", "rxgraph"]):
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File '{filepath}' does not exist.")

    before_modules = set(sys.modules)

    # Compile tasks dynamically. This naturally registers local AND imported tasks.
    _compile_tasks(filepath)

    # Discover all physical files involved.
    involved_files = {str(filepath)}

    # FIXED: Iterate using the new .tasks architecture layout smoothly
    for task in TaskSpec._parent_workflow.tasks.values():
        if task.func is not None:
            src_file = inspect.getsourcefile(task.func)
            if src_file:
                involved_files.add(src_file)

    # Intermediate local files loaded during compilation
    # We inspect sys.modules and include any file that lives inside the workflow's parent directory.
    project_dir = filepath.parent.resolve()
    for mod in list(sys.modules.values()):
        if hasattr(mod, "__file__") and mod.__file__:
            mod_path = Path(mod.__file__).resolve()

            # Check if the module is part of the local project (ignore stdlib and pip packages)
            try:
                if mod_path.is_relative_to(project_dir):
                    involved_files.add(str(mod_path))
            except AttributeError:
                # Fallback for Python versions older than 3.9
                if str(project_dir) in str(mod_path):
                    involved_files.add(str(mod_path))

    involved_files_list = list(involved_files)

    decorators_map = {}
    for f in involved_files_list:
        try:
            decorators_map.update(_extract_decorators_from_file(Path(f)))
        except Exception as e:
            print(f"Warning: Could not parse decorators for {f}: {e}", file=sys.stderr)

    try:
        nodes, edges = _build_call_graph(involved_files_list)
    except Exception as e:
        raise RuntimeError(f"Error building call graph with pyan3: {e}") from e
    finally:
        # Do not let local sibling modules leak into sys.modules between compilations.
        _purge_compiled_modules(before_modules, project_dir)

    enriched_nodes: list[dict[str, Any]] = []
    for node in nodes:
        short_name = node.split(".")[-1]
        decorators = decorators_map.get(short_name, [])

        enriched_node = {
            "id": node,
            "name": short_name,
            "decorators": decorators,
        }
        enriched_nodes.append(enriched_node)

    enriched_nodes = _filter_tasks_nodes(enriched_nodes)
    edges = _filter_tasks_edges(enriched_nodes, edges)

    result = {
        "file": str(filepath),
        "nodes": enriched_nodes,
        "edges": edges,
    }

    if format == "json":
        return json.dumps(result, indent=4)
    elif format == "rxgraph":
        return _to_rxgraph(result)
    elif format == "text":
        print(f"\n--- Call Graph Analysis: {filepath} ---\n")
        print("### NODES (User-Defined Functions) ###\n")
        if not enriched_nodes:
            print("  No functions found.")
        for n in enriched_nodes:
            dec_str = (
                f"\n    Decorators: [{', '.join(n['decorators'])}]"
                if n["decorators"]
                else ""
            )
            print(f"  - {n['id']}{dec_str}\n")

        print("### EDGES (Function Calls) ###")
        if not edges:
            print("  No explicit calls found.")
        for e in edges:
            print(f"  - {e['caller']}  -->  {e['callee']}")
        print()
    else:
        raise ValueError(f"Unknown format: {format}")
