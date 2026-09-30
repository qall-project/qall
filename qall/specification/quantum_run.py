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
import inspect

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from qall.interop.mapping import normalize_circuit_type


@dataclass(frozen=True)
class _QuantumType:
    """Statically inferred type of a value passed to qall.run()."""

    input_format: str


class _QuantumRunAnalyzer(ast.NodeVisitor):
    def __init__(
        self,
        source: str,
        import_statements: list[str] | None = None,
    ):
        self.source = source
        self.import_statements = import_statements or []
        self.runs: list[dict[str, Any]] = []
        self._types: dict[str, _QuantumType] = {}
        self._qall_names: set[str] = {"qall"}
        self._run_names: set[str] = set()
        self._module_aliases: dict[str, str] = {}
        self._symbol_aliases: dict[str, str] = {}
        self._tree = ast.parse(source)

        self._register_imports(self._tree)
        for import_statement in self.import_statements:
            try:
                self._register_imports(ast.parse(import_statement))
            except SyntaxError:
                continue

    def analyze(self) -> list[dict[str, Any]]:
        self.visit(self._tree)
        return self.runs

    def _register_imports(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound_name = alias.asname or alias.name.split(".")[0]
                    self._module_aliases[bound_name] = alias.name
                    if alias.name == "qall":
                        self._qall_names.add(bound_name)
            elif isinstance(node, ast.ImportFrom):
                if not node.module:
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    bound_name = alias.asname or alias.name
                    qualified_name = f"{node.module}.{alias.name}"
                    self._symbol_aliases[bound_name] = qualified_name
                    if node.module == "qall" and alias.name == "run":
                        self._run_names.add(bound_name)

    def visit_Assign(self, node: ast.Assign) -> Any:
        inferred = self._infer_type(node.value)
        for target in node.targets:
            self._assign_type(target, inferred)
        self.generic_visit(node)
        return None

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        inferred = self._infer_type(node.value) if node.value else None
        self._assign_type(node.target, inferred)
        self.generic_visit(node)
        return None

    def visit_NamedExpr(self, node: ast.NamedExpr) -> Any:
        inferred = self._infer_type(node.value)
        self._assign_type(node.target, inferred)
        self.generic_visit(node)
        return None

    def visit_Call(self, node: ast.Call) -> Any:
        if self._is_qall_run(node.func):
            if not node.args:
                self._add_run(None)
            else:
                self._add_run(self._infer_type(node.args[0]))
        self.generic_visit(node)
        return None

    def _is_qall_run(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Attribute):
            return (
                node.attr == "run"
                and isinstance(node.value, ast.Name)
                and node.value.id in self._qall_names
            )
        return isinstance(node, ast.Name) and node.id in self._run_names

    def _assign_type(
        self,
        target: ast.AST,
        inferred: _QuantumType | None,
    ) -> None:
        if isinstance(target, ast.Name):
            if inferred is None:
                self._types.pop(target.id, None)
            else:
                self._types[target.id] = inferred
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                if isinstance(element, ast.Name):
                    self._types.pop(element.id, None)

    def _infer_type(self, node: ast.AST | None) -> _QuantumType | None:
        if node is None:
            return None

        if isinstance(node, ast.Name):
            return self._types.get(node.id)

        if isinstance(node, ast.Call):
            return self._infer_constructor_type(node.func)

        if isinstance(node, ast.Attribute):
            qualified_name = self._qualified_name(node)
            if qualified_name:
                return self._type_from_qualified_name(qualified_name)
        return None

    def _infer_constructor_type(self, func: ast.AST) -> _QuantumType | None:
        qualified_name = self._qualified_name(func)

        if not qualified_name:
            return None

        return self._type_from_qualified_name(qualified_name)

    def _type_from_qualified_name(
        self,
        qualified_name: str,
    ) -> _QuantumType | None:
        normalized = normalize_circuit_type(qualified_name)

        if normalized:
            return _QuantumType(input_format=normalized)
        return None

    def _qualified_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in self._symbol_aliases:
                return self._symbol_aliases[node.id]
            if node.id in self._module_aliases:
                return self._module_aliases[node.id]
            return node.id

        if isinstance(node, ast.Attribute):
            parent = self._qualified_name(node.value)
            if parent:
                return f"{parent}.{node.attr}"
        return None

    def _add_run(self, quantum_type: _QuantumType | None) -> None:
        if quantum_type is None:
            entry = {
                "input_format": None,
                "dynamic": True,
            }
        else:
            entry = {
                "input_format": quantum_type.input_format,
                "dynamic": False,
            }
        if entry not in self.runs:
            self.runs.append(entry)


def extract_quantum_runs(
    func: Callable,
    source: str,
    local_dependencies: dict[str, str],
    imports: dict[str, list[str]],
) -> list[dict[str, Any]]:
    sources: list[tuple[str, str, list[str]]] = [
        (
            getattr(func, "__name__", "<task>"),
            source,
            imports.get("external_imports", []),
        )
    ]

    dependency_imports = _extract_import_statements_from_source_file(func)

    for name, dependency_source in local_dependencies.items():
        sources.append(
            (
                name,
                dependency_source,
                dependency_imports,
            )
        )

    runs: list[dict[str, Any]] = []

    for _, source_code, import_statements in sources:
        try:
            analyzer = _QuantumRunAnalyzer(
                source_code,
                import_statements=import_statements,
            )
            for run in analyzer.analyze():
                if run not in runs:
                    runs.append(run)
        except (SyntaxError, TypeError):
            continue
    return runs


def _extract_import_statements_from_source_file(
    func: Callable,
) -> list[str]:
    try:
        source_file = inspect.getsourcefile(func)
        if not source_file:
            return []
        path = Path(source_file)
        if not path.exists():
            return []
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return [
            ast.unparse(node)
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
    except (OSError, SyntaxError, TypeError):
        return []
