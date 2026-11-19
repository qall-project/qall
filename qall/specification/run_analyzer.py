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

import ast
from typing import Any, Callable, Optional

_QALL_MODULES = frozenset({"qall", "qall.sdk"})


class _RunAnalyzer(ast.NodeVisitor):
    """
    Extracts static workflow/task references from `qall.run(ref, ...)`.

    This visitor solely looks for static string hashes/tags pointing to tasks.
    It deliberately raises an error if the target is dynamic (e.g. built at runtime)
    or if a user attempts to pass a quantum circuit (which belongs in `qall.sample`).
    """

    def __init__(self, source: str, task_name: str = "<task>"):
        self.task_name = task_name
        self.external_runs: list[str] = []
        self._str_vars: dict[str, Optional[str]] = {}
        self._qall_names: set[str] = {"qall"}
        self._run_names: set[str] = set()

        self._tree = ast.parse(source)
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "qall":
                        self._qall_names.add(a.asname or "qall")
            elif isinstance(node, ast.ImportFrom) and node.module in _QALL_MODULES:
                for a in node.names:
                    if a.name == "run":
                        self._run_names.add(a.asname or "run")

    def analyze(self) -> list[str]:
        self.visit(self._tree)
        return self.external_runs

    def visit_Assign(self, node: ast.Assign) -> Any:
        for target in node.targets:
            self._bind(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        self._bind(node.target, node.value)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> Any:
        self._bind(node.target, node.value)
        self.generic_visit(node)

    def _bind(self, target: ast.AST, value: Optional[ast.AST]) -> None:
        """Tracks local string variables to resolve things like `ref = "wf:v1"; qall.run(ref)`"""
        if isinstance(target, (ast.Tuple, ast.List)):
            for el in target.elts:
                if isinstance(el, ast.Name):
                    self._str_vars.pop(el.id, None)
            return
        if not isinstance(target, ast.Name):
            return

        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            resolved: Optional[str] = value.value
        elif isinstance(value, ast.Name) and value.id in self._str_vars:
            resolved = self._str_vars[value.id]
        else:
            resolved = None

        if target.id in self._str_vars and self._str_vars[target.id] != resolved:
            self._str_vars[target.id] = None
        else:
            self._str_vars[target.id] = resolved

    def visit_Call(self, node: ast.Call) -> Any:
        is_run = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in self._qall_names
        ) or (isinstance(node.func, ast.Name) and node.func.id in self._run_names)

        if is_run:
            ref = self._resolve_target(node)
            if ref not in self.external_runs:
                self.external_runs.append(ref)
        self.generic_visit(node)

    def _resolve_target(self, call: ast.Call) -> str:
        target = (
            call.args[0]
            if call.args
            else next(
                (kw.value for kw in call.keywords if kw.arg in ("target", "workflow")),
                None,
            )
        )
        if target is None:
            raise ValueError(
                f"Task '{self.task_name}' calls qall.run() without a target."
            )

        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            val = target.value.strip()
        elif isinstance(target, ast.Name) and target.id in self._str_vars:
            val = (self._str_vars[target.id] or "").strip()
        elif isinstance(target, (ast.JoinedStr, ast.BinOp, ast.Name, ast.Call)):
            # We strictly reject dynamic targets (f-strings, concatenations) because
            # the Workflow DAG must be completely known at compile-time.
            raise ValueError(
                f"Task '{self.task_name}' calls qall.run({ast.unparse(target)}) with a dynamic or unresolvable target."
            )
        else:
            # We reject circuits. They belong in qall.sample().
            raise ValueError(
                f"Task '{self.task_name}' passes a non-string target ({ast.unparse(target)}) to qall.run(); "
                "use qall.sample() for quantum circuits."
            )

        if not val:
            raise ValueError(
                f"Task '{self.task_name}' calls qall.run() with an empty target."
            )
        return val


def extract_runs(
    func: Callable,
    source: str,
    local_dependencies: dict[str, str],
) -> list[str]:
    """Extracts all static `qall.run()` references across a task and its local helpers."""
    task_name = getattr(func, "__name__", "<task>")
    results: list[str] = []

    for code in [source, *local_dependencies.values()]:
        try:
            for ref in _RunAnalyzer(code, task_name=task_name).analyze():
                if ref not in results:
                    results.append(ref)
        except SyntaxError:
            continue

    return results
