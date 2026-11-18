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
from pathlib import Path
from typing import Any, Callable, Optional

from qall.interop import normalize_circuit_type, is_known_circuit_type

_QALL_MODULES = frozenset({"qall", "qall.sdk"})


class _SampleAnalyzer(ast.NodeVisitor):
    """
    Extracts and validates `qall.sample(circuit, ...)` calls.

    This visitor runs on the abstract syntax tree (AST) of user tasks.
    It tracks bindings (assignments) to recognize which format of quantum circuit
    is passed to `qall.sample()`.
    """

    def __init__(
        self,
        source: str,
        import_statements: list[str] | None = None,
        task_name: str = "<task>",
        known_circuits: dict[str, str] | None = None,
        collect_calls: bool = True,
    ):
        self.task_name = task_name
        self.quantum_runs: list[dict[str, Any]] = []
        self._circuits: dict[str, str] = dict(known_circuits or {})
        self._qall_names: set[str] = {"qall"}
        self._sample_names: set[str] = set()
        self._aliases: dict[str, str] = {}

        # We allow running the analyzer solely to capture circuit definitions
        # (like `@cudaq.kernel`) without flagging `qall.sample()` calls yet.
        self._collect_calls = collect_calls

        self._tree = ast.parse(source)
        for stmt in [source, *(import_statements or [])]:
            self._collect_imports(stmt)

    def _collect_imports(self, code: str) -> None:
        """
        Extract module and function aliases to support user syntax like:
        `from cudaq import kernel as my_kernel` or `import qall as q`.
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    bound = a.asname or a.name.split(".")[0]
                    self._aliases[bound] = a.name
                    if a.name == "qall":
                        self._qall_names.add(bound)
            elif isinstance(node, ast.ImportFrom) and node.module:
                for a in node.names:
                    if a.name != "*":
                        bound = a.asname or a.name
                        self._aliases[bound] = f"{node.module}.{a.name}"
                        if node.module in _QALL_MODULES and a.name == "sample":
                            self._sample_names.add(bound)

    def analyze(self) -> list[dict[str, Any]]:
        self.visit(self._tree)
        return self.quantum_runs

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        # CUDA-Q Corner Case: cudaq kernels are functions, not variables.
        # We must flag the function name itself as a `cudaq` circuit if it has the `@cudaq.kernel` decorator.
        for dec in node.decorator_list:
            expr = dec.func if isinstance(dec, ast.Call) else dec
            if self._qname(expr) == "cudaq.kernel":
                self._circuits[node.name] = "cudaq"

        # If the function returns a known circuit type or receives one in arguments
        if fmt := self._infer_format(node.returns, strict=False):
            self._circuits[node.name] = fmt

        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            if fmt := self._infer_format(arg.annotation, strict=False):
                self._circuits[arg.arg] = fmt

        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> Any:
        for target in node.targets:
            self._bind(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        self._bind(node.target, node.value, node.annotation)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> Any:
        self._bind(node.target, node.value)
        self.generic_visit(node)

    def _bind(
        self, target: ast.AST, value: Optional[ast.AST], ann: Optional[ast.AST] = None
    ) -> None:
        """Propagate circuit types through local variable assignments."""
        if isinstance(target, (ast.Tuple, ast.List)):
            for el in target.elts:
                if isinstance(el, ast.Name):
                    self._circuits.pop(el.id, None)
            return
        if not isinstance(target, ast.Name):
            return

        # If the RHS is a known circuit type (e.g. `cirq.Circuit()`), map the variable name
        fmt = self._infer_format(value, strict=False) or self._infer_format(
            ann, strict=False
        )
        if fmt:
            self._circuits[target.id] = fmt
        else:
            self._circuits.pop(target.id, None)

    def visit_Call(self, node: ast.Call) -> Any:
        if not self._collect_calls:
            self.generic_visit(node)
            return

        is_sample = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "sample"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in self._qall_names
        ) or (isinstance(node.func, ast.Name) and node.func.id in self._sample_names)

        if is_sample:
            arg = (
                node.args[0]
                if node.args
                else next(
                    (kw.value for kw in node.keywords if kw.arg == "circuit"), None
                )
            )

            if arg is None:
                raise ValueError(
                    f"Task '{self.task_name}' calls qall.sample() without a circuit."
                )

            # Corner case: Ensure users don't mix up `run` and `sample`.
            # A string literal or f-string meant for `qall.run(ref)` passed to `qall.sample()` is fatal.
            if isinstance(arg, ast.JoinedStr) or (
                isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            ):
                raise ValueError(
                    f"Task '{self.task_name}' passes a string to qall.sample(); use qall.run() for workflows/tasks."
                )

            # If the circuit type is unsupported or cannot be resolved, this raises ValueError
            entry = {"input_format": self._infer_format(arg, strict=True)}
            if entry not in self.quantum_runs:
                self.quantum_runs.append(entry)

        self.generic_visit(node)

    def _infer_format(self, node: Optional[ast.AST], *, strict: bool) -> Optional[str]:
        if node is None:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                node = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                return None

        # Resolve local variables (`qc`)
        if isinstance(node, ast.Name) and node.id in self._circuits:
            return self._circuits[node.id]

        qname = self._qname(node.func if isinstance(node, ast.Call) else node)

        if qname:
            if qname in self._circuits:
                return self._circuits[qname]
            try:
                # Resolve package paths (`qiskit.circuit.QuantumCircuit` -> `qiskit`)
                norm = normalize_circuit_type(qname)
                return norm
            except ValueError as exc:
                if strict:
                    raise ValueError(
                        f"Task '{self.task_name}' uses unsupported circuit type {qname!r} in qall.sample()."
                    ) from exc
                return None

        if strict:
            raise ValueError(
                f"Task '{self.task_name}' calls qall.sample({ast.unparse(node)}) with an unsupported circuit type."
            )
        return None

    def _qname(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return self._aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            parent = self._qname(node.value)
            return f"{parent}.{node.attr}" if parent else None
        return None


def extract_samples(
    func: Callable,
    source: str,
    local_dependencies: dict[str, str],
    imports: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Extracts and validates `qall.sample()` calls across a task and its local helpers."""
    task_name = getattr(func, "__name__", "<task>")
    file_imports = _file_imports(func)
    results: list[dict[str, Any]] = []
    known: dict[str, str] = {}

    # 1. Pre-scan the defining module for @cudaq.kernel and circuit-annotated symbols.
    # Why? `bell` might be defined at the top of the file, outside the local helpers actually called.
    try:
        src_file = inspect.getsourcefile(func)
        if src_file and Path(src_file).exists():
            mod_ctx = _SampleAnalyzer(
                Path(src_file).read_text(encoding="utf-8"),
                task_name=task_name,
                collect_calls=False,
            )
            mod_ctx.analyze()
            known.update(mod_ctx._circuits)
    except (OSError, SyntaxError, TypeError):
        pass

    # 2. Scan bundled local helper functions for intermediate variables
    for dep_source in local_dependencies.values():
        try:
            sub = _SampleAnalyzer(
                dep_source, file_imports, task_name=task_name, known_circuits=known
            )
            for item in sub.analyze():
                if item not in results:
                    results.append(item)
            known.update(sub._circuits)
        except SyntaxError:
            continue

    # 3. Scan the main task source with complete circuit resolution context
    main = _SampleAnalyzer(
        source,
        imports.get("external_imports", []),
        task_name=task_name,
        known_circuits=known,
    )
    for item in main.analyze():
        if item not in results:
            results.append(item)
    return results


def _file_imports(func: Callable) -> list[str]:
    try:
        src = inspect.getsourcefile(func)
        if not src or not Path(src).exists():
            return []
        tree = ast.parse(Path(src).read_text(encoding="utf-8"))
        return [
            ast.unparse(n)
            for n in tree.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
    except (OSError, SyntaxError, TypeError):
        return []
