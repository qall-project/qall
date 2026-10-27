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
import site
import sys
from collections import deque
from pathlib import Path

import rustworkx as rx
from rustworkx import DAGWouldCycle
from typing import Any, Literal

from .imports import (
    discover_external_imports,
    discover_file_global_imports,
    lenient_imports,
    map_imports_to_packages,
)
from .task import DECORATORS, TaskSpec, _PLATLIB_PATH, _PURELIB_PATH, _STDLIB_PATH

logger = logging.getLogger(__name__)

# Directories that contain installed third-party packages. Used by
# _is_stdlib_or_site_packages to tell "local project code" apart from pip
# packages, even when a virtualenv is nested inside the project directory
# (e.g. macOS layouts like `<project>/qall-quark/lib/python3.14/site-packages/`).
_SITE_PACKAGES_DIRS = set()
try:
    for _p in site.getsitepackages():
        _SITE_PACKAGES_DIRS.add(Path(_p).resolve())
except Exception:  # pragma: no cover - depends on the host Python
    pass
try:
    _SITE_PACKAGES_DIRS.add(Path(site.getusersitepackages()).resolve())
except Exception:  # pragma: no cover - depends on the host Python
    pass


def _is_stdlib_or_site_packages(path: str | Path) -> bool:
    """True when ``path`` belongs to the Python stdlib or to an installed
    third-party package (site-packages / dist-packages).

    A module must never be treated as a "local project file" just because the
    virtualenv that provides it happens to live under the workflow's directory:
    that would feed third-party sources (e.g. ``docker``) to the pyan3 call
    graph and crash compilation on layouts with a nested venv.
    """
    p = Path(path).resolve()

    # Robust string check: catches site-packages inside nested venvs and also
    # plain "dist-packages" names on some distributions.
    if "site-packages" in str(p) or "dist-packages" in str(p):
        return True

    bases = (_STDLIB_PATH, _PURELIB_PATH, _PLATLIB_PATH) + tuple(_SITE_PACKAGES_DIRS)
    for base in bases:
        try:
            if p.is_relative_to(base):
                return True
        except (ValueError, OSError):
            continue
    return False


def _load_pyan():
    """Lazily import pyan3, raising a clear error instead of exiting the process."""
    try:
        from pyan.analyzer import CallGraphVisitor, Flavor

        return CallGraphVisitor, Flavor
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "pyan3>=2.9.0 is required to build qall workflow call graphs. "
            "Install it with: pip install 'pyan3>=2.9.0,<3'"
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


def _build_call_graph_from_sources(
    sources: dict[str, Path],
) -> tuple[list[str], list[dict[str, str]]]:
    """
    Builds the nodes and edges of the static call graph using pyan3's
    in-memory ``from_sources`` API.

    :param sources: mapping ``{pyan module_name -> source file path}`` for every
        user module the workflow pulls in (see ``_discover_user_sources``). The
        module names are fully qualified (matching ``sys.modules``), so pyan does
        not have to infer them from file paths and nothing is missed regardless of
        where the files live on disk.
    :return: a list of *qualified* node names (e.g. ``pkg.mod.func``) and a list
        of edge dicts whose ``caller``/``callee`` are qualified node names.
    """
    CallGraphVisitor, Flavor = _load_pyan()

    files = []
    for module_name, path in sources.items():
        try:
            source = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"Source file disappeared while building the call graph: {path}"
            ) from exc
        files.append((source, module_name))

    # from_sources() runs the two-pass analysis itself (no extra process() call).
    visitor = CallGraphVisitor.from_sources(files)

    def _local(node) -> bool:
        """A real, defined callable/class in an analyzed user module.

        Unknown nodes (``namespace is None``: wildcards, unresolvable module
        members) and synthetic structural nodes (modules, scopes, plain names)
        are excluded: they are pyan internals, not user code. A future pyan
        version flattening this shape will surface here as a test failure, not
        a silent empty graph.
        """
        return (
            node.defined
            and node.namespace is not None
            and node.flavor
            in {
                Flavor.FUNCTION,
                Flavor.METHOD,
                Flavor.STATICMETHOD,
                Flavor.CLASSMETHOD,
                Flavor.CLASS,
            }
        )

    nodes_set: set[str] = set()
    edges_list: list[dict[str, str]] = []

    # Defined nodes (functions/classes), using the *qualified* name as identity.
    for bucket in visitor.nodes.values():
        for node in bucket:
            if _local(node):
                nodes_set.add(node.get_name())

    # Call edges between local nodes (unknown/import targets are filtered out).
    for src_node, target_nodes in visitor.uses_edges.items():
        if not _local(src_node):
            continue
        for tgt_node in target_nodes:
            if _local(tgt_node):
                edges_list.append(
                    {"caller": src_node.get_name(), "callee": tgt_node.get_name()}
                )

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

    Nodes carry a qualified pyan identity (``qualified_name``) plus the short
    ``name`` used by the task registry. Bridging uses the qualified identity so
    two same-named functions in different modules cannot be conflated; the
    returned edges are expressed with short task names (the registry contract).

    :param nodes: List of nodes
    :param edges: List of edges (qualified caller/callee)
    :return: Filtered list of edges (short task names)
    """
    # Qualified name -> short name for every valid task node.
    valid_tasks: dict[str, str] = {
        node["qualified_name"]: node["name"] for node in nodes
    }
    valid_names: set[str] = set(valid_tasks)

    # Qualified name -> source of each task, used to prune import-only edges below.
    task_sources: dict[str, str] = {
        node["qualified_name"]: node["task"].source for node in nodes
    }

    # caller -> callees adjacency (qualified names)
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        caller, callee = edge["caller"], edge["callee"]

        # pyan3 records module-level imports as "uses", producing spurious edges
        # between two tasks (e.g. `from other import remote` yields `main -> remote`
        # even when `main` never calls `remote`). If the caller task never mentions
        # the callee's short name in its own source, the edge is an import, not a call.
        # Non-task callers are left untouched so BFS bridging still works.
        if caller in task_sources and callee in valid_names:
            callee_short = callee.rsplit(".", 1)[-1]
            if callee_short not in task_sources[caller]:
                continue

        adjacency.setdefault(caller, set()).add(callee)

    filtered_edges: set[tuple[str, str]] = set()
    for node in nodes:
        source = node["qualified_name"]

        queue = deque([source])
        seen = {source}

        while queue:
            current = queue.popleft()
            for target in adjacency.get(current, ()):
                if target in seen:
                    continue
                seen.add(target)

                if target in valid_names:
                    # Task boundary: record the edge and do not traverse through
                    # the callee task (that task owns its own outgoing edges).
                    filtered_edges.add((source, target))
                else:
                    # Non-task intermediate: keep traversing to find real tasks.
                    queue.append(target)

    # Map back to short task names for the registry and the serialized graph.
    return [
        {"caller": valid_tasks[caller], "callee": valid_tasks[callee]}
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

    # Statically discover the workflow file's *global* third-party imports
    # (module-body scope only) and map them to pip package names. These become
    # the workflow's root-scope dependencies, auto-added to every task defined
    # in the file. Imports made inside task bodies (task-scope) are not
    # auto-added: they are the user's per-task piprequirements responsibility.
    TaskSpec._discovered_requirements = map_imports_to_packages(
        discover_file_global_imports(filepath)
    )

    # Statically discover the *project's* third-party imports so missing
    # packages do not crash compilation: they are stubbed during execution
    # below. Unlike _discovered_requirements, this stays deliberately broad so
    # task-scope and sibling imports are covered too.
    discovered = discover_external_imports(parent_dir)

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
    """True if a module physically lives inside `directory` (file or namespace).

    Stdlib and installed third-party packages are excluded: a nested virtualenv
    under ``directory`` must never be treated as local project code.
    """
    file = getattr(module, "__file__", None)
    if file:
        try:
            p = Path(file).resolve()
            return p.is_relative_to(directory) and not _is_stdlib_or_site_packages(p)
        except (ValueError, OSError):
            return False

    for path in getattr(module, "__path__", ()) or ():
        try:
            p = Path(path).resolve()
            if p.is_relative_to(directory) and not _is_stdlib_or_site_packages(p):
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


def _pyan_module_name(module: Any) -> str:
    """The fully qualified module name pyan3 expects for a sys.modules module.

    Package ``__init__`` modules are given the ``<pkg>.__init__`` suffix so that
    pyan's relative-import resolution works (its contract for in-memory sources).
    """
    name = getattr(module, "__name__", None) or ""
    file = getattr(module, "__file__", None)
    if file and Path(file).name == "__init__.py":
        return f"{name}.__init__"
    return name


def _discover_user_sources(
    workflow_filepath: Path, *, start_modules: set[str]
) -> dict[str, Path]:
    """Map {pyan module name -> source path} for all user code the workflow pulls in.

    Discovery is import-based, not path-glob-based: after ``_compile_tasks`` runs
    the workflow, every module it imported is recorded in ``sys.modules`` under its
    natural, fully qualified name. That authoritative name is exactly what pyan's
    ``from_sources`` needs, and the file's location on disk is irrelevant — which
    also fixes the legacy gap where out-of-tree user helper modules were dropped.

    Rules per module ``m`` in ``sys.modules`` (post-compile, minus ``start_modules``):
      - skip if no ``__file__`` (builtins / lenient-import stubs have ``__file__`` None)
      - skip if ``_is_stdlib_or_site_packages`` (stdlib / pip / nested venv)
      - skip if ``__name__`` is ``qall`` or starts with ``qall.`` (excludes qall
        itself in a dev checkout, including the synthetic ``qall.plugins.*`` compile
        namespace)
      - skip if the file is not ``.py``
      - include regardless of whether the file lives under the workflow's directory

    The workflow file itself is seeded separately: at compile time it is registered
    under the synthetic ``qall.plugins.<stem>`` name, so its real identity here is
    just its stem (matching how pyan would name a top-level module).

    :param workflow_filepath: the workflow file just compiled.
    :param start_modules: snapshot of ``sys.modules`` taken before compilation; any
        module already present is not user code pulled in by *this* workflow, so it
        is ignored (prevents cross-compilation leakage in long-lived processes).
    :return: mapping ``{pyan module name -> Path}``.
    """
    sources: dict[str, Path] = {}
    seen_paths: set[Path] = {workflow_filepath.resolve()}

    def _add(module_name: str, path: Path) -> None:
        path = path.resolve()
        if path in seen_paths:
            return
        existing = sources.get(module_name)
        if existing is not None and existing != path:
            raise ValueError(
                f"Module name collision while discovering workflow sources: "
                f"{module_name!r} maps to both {existing} and {path}. "
                "Rename one of the modules to disambiguate them."
            )
        sources[module_name] = path
        seen_paths.add(path)

    # The workflow file itself (its synthetic qall.plugins.<stem> sys.modules entry
    # is skipped below, so seed it under its natural module name).
    sources[workflow_filepath.stem] = workflow_filepath.resolve()

    for name, module in list(sys.modules.items()):
        if name in start_modules:
            continue
        if name == "qall" or name.startswith("qall."):
            continue
        file = getattr(module, "__file__", None)
        if not file:
            continue  # builtins / lenient-import stubs
        path = Path(file)
        if not path.name.endswith(".py"):
            continue  # .so / .pyc / .pyi handled elsewhere or not analyzable
        if _is_stdlib_or_site_packages(path):
            continue
        _add(_pyan_module_name(module), path)

    # Belt and suspenders: a task function could come from a file that is not in
    # sys.modules (unusual, but the graph must never silently miss a task).
    parent = getattr(TaskSpec, "_parent_workflow", None)
    tasks = getattr(parent, "tasks", None) or {}
    for task in tasks.values():
        func = getattr(task, "func", None)
        if func is None:
            continue
        src_file = inspect.getsourcefile(func)
        if not src_file:
            continue
        path = Path(src_file)
        if not path.name.endswith(".py") or _is_stdlib_or_site_packages(path):
            continue
        # Prefer the sys.modules name when this exact file is loaded somewhere,
        # else fall back to a natural top-level name based on the file stem.
        module_name = next(
            (
                _pyan_module_name(m)
                for n, m in sys.modules.items()
                if getattr(m, "__file__", None)
                and Path(m.__file__).resolve() == path.resolve()
            ),
            path.stem,
        )
        _add(module_name, path)

    return sources


def generate_call_graph(filepath: Path, format: Literal["text", "json", "rxgraph"]):
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File '{filepath}' does not exist.")

    before_modules = set(sys.modules)

    # Compile tasks dynamically. This naturally registers local AND imported tasks.
    _compile_tasks(filepath)

    # Discover every user source file the workflow pulled in, mapped to the fully
    # qualified module name pyan3's from_sources API needs (sys.modules-derived).
    # Covers in-tree siblings, nested packages and out-of-tree helper modules as
    # long as they were imported; stdlib, pip packages and qall itself are excluded.
    sources = _discover_user_sources(filepath, start_modules=before_modules)

    decorators_map = {}
    for path in dict.fromkeys(sources.values()):
        try:
            decorators_map.update(_extract_decorators_from_file(path))
        except Exception as e:
            print(
                f"Warning: Could not parse decorators for {path}: {e}", file=sys.stderr
            )

    project_dir = filepath.parent.resolve()
    try:
        nodes, edges = _build_call_graph_from_sources(sources)
    except Exception as e:
        raise RuntimeError(
            f"qall could not build the workflow call graph with pyan3: {e}"
        ) from e
    finally:
        # Do not let local sibling modules (in-tree or out-of-tree) leak into
        # sys.modules between compilations.
        _purge_compiled_modules(before_modules, project_dir)
        discovered_paths = {p.resolve() for p in sources.values()}
        for name, module in list(sys.modules.items()):
            if name in before_modules:
                continue
            file = getattr(module, "__file__", None)
            if file and Path(file).resolve() in discovered_paths:
                sys.modules.pop(name, None)

    enriched_nodes: list[dict[str, Any]] = []
    for node in nodes:
        # node is the qualified pyan identity (e.g. "pkg.mod.func"); the task
        # registry and the serialized graph speak short names.
        short_name = node.rsplit(".", 1)[-1] if "." in node else node
        decorators = decorators_map.get(short_name, [])

        enriched_node = {
            "id": node,
            "name": short_name,
            "qualified_name": node,
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
