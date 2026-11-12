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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from qall.interop.mapping import normalize_circuit_type


@dataclass(frozen=True)
class _QuantumType:
    """Statically inferred circuit format passed to qall.run()."""

    input_format: str


@dataclass
class RunAnalysisResult:
    """Combined static analysis output for qall.run() calls in a task."""

    quantum_runs: list[dict[str, Any]] = field(default_factory=list)
    external_runs: list[str] = field(default_factory=list)


def _is_string_annotation(annotation: Optional[ast.AST]) -> bool:
    """True when a type annotation statically declares str or Optional[str]."""
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return False
    if isinstance(annotation, ast.Name):
        return annotation.id == "str"
    if isinstance(annotation, ast.Subscript):
        return any(
            isinstance(sub, ast.Name) and sub.id == "str"
            for sub in ast.walk(annotation.slice)
        )
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_string_annotation(annotation.left) or _is_string_annotation(
            annotation.right
        )
    return False


def _looks_like_str(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant) and isinstance(node.value, str)
    ) or isinstance(node, ast.JoinedStr)


def _is_dynamic_str_expr(node: ast.AST) -> bool:
    """True for string expressions whose value cannot be deduced at compile time."""
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return _looks_like_str(node.left) or _looks_like_str(node.right)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
        and _looks_like_str(node.func.value)
    )


class _RunAnalyzer(ast.NodeVisitor):
    """Single-pass AST visitor classifying qall.run() calls into quantum or external runs."""

    def __init__(
        self,
        source: str,
        import_statements: list[str] | None = None,
        task_name: str = "<task>",
    ):
        self.task_name = task_name
        self.quantum_runs: list[dict[str, Any]] = []
        self.external_runs: list[str] = []

        self._circuit_types: dict[str, _QuantumType] = {}
        # Variable name -> resolved static string, or None if known to be a dynamic str
        self._str_vars: dict[str, Optional[str]] = {}
        self._qall_names: set[str] = {"qall"}
        self._run_names: set[str] = set()
        self._module_aliases: dict[str, str] = {}
        self._symbol_aliases: dict[str, str] = {}

        self._tree = ast.parse(source)
        self._register_imports(self._tree)
        for stmt in import_statements or []:
            try:
                self._register_imports(ast.parse(stmt))
            except SyntaxError:
                continue

    def analyze(self) -> RunAnalysisResult:
        self.visit(self._tree)
        return RunAnalysisResult(
            quantum_runs=self.quantum_runs,
            external_runs=self.external_runs,
        )

    def _register_imports(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    self._module_aliases[bound] = alias.name
                    if alias.name == "qall":
                        self._qall_names.add(bound)
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    bound = alias.asname or alias.name
                    self._symbol_aliases[bound] = f"{node.module}.{alias.name}"
                    if node.module == "qall" and alias.name == "run":
                        self._run_names.add(bound)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            if _is_string_annotation(arg.annotation):
                self._str_vars[arg.arg] = None
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> Any:
        for target in node.targets:
            self._track_binding(target, node.value, annotated_str=False)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        self._track_binding(
            node.target,
            node.value,
            annotated_str=_is_string_annotation(node.annotation),
        )
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> Any:
        self._track_binding(node.target, node.value, annotated_str=False)
        self.generic_visit(node)

    def _track_binding(
        self,
        target: ast.AST,
        value: Optional[ast.AST],
        annotated_str: bool,
    ) -> None:
        if not isinstance(target, ast.Name):
            if isinstance(target, (ast.Tuple, ast.List)):
                for el in target.elts:
                    if isinstance(el, ast.Name):
                        self._circuit_types.pop(el.id, None)
                        self._str_vars.pop(el.id, None)
            return

        name = target.id
        # 1. Track string bindings (for external workflow/task references)
        if (
            value is not None
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            resolved: Optional[str] = value.value
            is_str = True
        elif (
            value is not None
            and isinstance(value, ast.Name)
            and value.id in self._str_vars
        ):
            resolved = self._str_vars[value.id]
            is_str = True
        elif (value is not None and _is_dynamic_str_expr(value)) or annotated_str:
            resolved = None
            is_str = True
        else:
            is_str = False

        if is_str:
            self._circuit_types.pop(name, None)
            if name in self._str_vars and self._str_vars[name] != resolved:
                self._str_vars[name] = None
            else:
                self._str_vars[name] = resolved
            return

        # 2. Track quantum circuit type bindings
        self._str_vars.pop(name, None)
        inferred = self._infer_circuit_type(value)
        if inferred is None:
            self._circuit_types.pop(name, None)
        else:
            self._circuit_types[name] = inferred

    def visit_Call(self, node: ast.Call) -> Any:
        if self._is_qall_run(node.func):
            target = self._extract_target_node(node)
            if target is not None and self._is_string_target(target):
                ref = self._resolve_static_str(target)
                if ref not in self.external_runs:
                    self.external_runs.append(ref)
            else:
                q_type = self._infer_circuit_type(target)
                self._add_quantum_run(q_type)
        self.generic_visit(node)

    def _is_qall_run(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Attribute):
            return (
                node.attr == "run"
                and isinstance(node.value, ast.Name)
                and node.value.id in self._qall_names
            )
        return isinstance(node, ast.Name) and node.id in self._run_names

    @staticmethod
    def _extract_target_node(call: ast.Call) -> Optional[ast.AST]:
        if call.args:
            return call.args[0]
        for kw in call.keywords:
            if kw.arg in ("target", "workflow"):
                return kw.value
        return None

    def _is_string_target(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return True
        if isinstance(node, ast.Name) and node.id in self._str_vars:
            return True
        return _is_dynamic_str_expr(node)

    def _resolve_static_str(self, node: ast.AST) -> str:
        """Returns the static reference string or raises ValueError if dynamic/empty."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            cleaned = node.value.strip()
            if not cleaned:
                raise ValueError(
                    f"Task '{self.task_name}' calls qall.run() with an empty string."
                )
            return cleaned
        if isinstance(node, ast.Name) and node.id in self._str_vars:
            val = self._str_vars[node.id]
            if not val or not val.strip():
                raise ValueError(
                    f"Task '{self.task_name}' calls qall.run({node.id!r}) with an unresolvable string."
                )
            return val.strip()
        raise ValueError(
            f"Task '{self.task_name}' calls qall.run({ast.unparse(node)}) with a dynamic string."
        )

    def _infer_circuit_type(self, node: Optional[ast.AST]) -> Optional[_QuantumType]:
        if node is None:
            return None
        if isinstance(node, ast.Name):
            return self._circuit_types.get(node.id)
        if isinstance(node, ast.Call):
            qname = self._qualified_name(node.func)
            return _QuantumType(normalize_circuit_type(qname)) if qname else None
        if isinstance(node, ast.Attribute):
            qname = self._qualified_name(node)
            return _QuantumType(normalize_circuit_type(qname)) if qname else None
        return None

    def _qualified_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return self._symbol_aliases.get(
                node.id, self._module_aliases.get(node.id, node.id)
            )
        if isinstance(node, ast.Attribute):
            parent = self._qualified_name(node.value)
            return f"{parent}.{node.attr}" if parent else None
        return None

    def _add_quantum_run(self, q_type: Optional[_QuantumType]) -> None:
        entry = (
            {"input_format": None, "dynamic": True}
            if q_type is None
            else {"input_format": q_type.input_format, "dynamic": False}
        )
        if entry not in self.quantum_runs:
            self.quantum_runs.append(entry)


def extract_runs(
    func: Callable,
    source: str,
    local_dependencies: dict[str, str],
    imports: dict[str, list[str]],
) -> RunAnalysisResult:
    """Analyzes a task and its local helpers to extract quantum and external runs."""
    task_name = getattr(func, "__name__", "<task>")
    sources: list[tuple[str, list[str]]] = [
        (source, imports.get("external_imports", []))
    ]
    file_imports = _extract_file_imports(func)

    for dep_source in local_dependencies.values():
        sources.append((dep_source, file_imports))

    result = RunAnalysisResult()
    for code, imp in sources:
        try:
            partial = _RunAnalyzer(code, imp, task_name=task_name).analyze()
        except SyntaxError:
            continue
        for q_run in partial.quantum_runs:
            if q_run not in result.quantum_runs:
                result.quantum_runs.append(q_run)
        for ext_run in partial.external_runs:
            if ext_run not in result.external_runs:
                result.external_runs.append(ext_run)

    return result


def _extract_file_imports(func: Callable) -> list[str]:
    try:
        src_file = inspect.getsourcefile(func)
        if not src_file or not Path(src_file).exists():
            return []
        tree = ast.parse(Path(src_file).read_text(encoding="utf-8"))
        return [
            ast.unparse(n)
            for n in tree.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
    except (OSError, SyntaxError, TypeError):
        return []
