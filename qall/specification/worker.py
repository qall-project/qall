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
import textwrap
import types
import sys
import importlib

from pathlib import Path
from types import ModuleType
from typing import Any, Optional

from dataclasses import dataclass, field
from dataclasses_json import config, dataclass_json

from qall.provider.worker import QuantumWorker
from qall.interop.mapping import normalize_circuit_type, normalize_result_type

from .imports import (
    discover_external_imports,
    discover_file_global_imports,
    lenient_imports,
    map_imports_to_packages,
    merge_requirements,
)
from .task import (
    _bundle_local_dependencies,
    _extract_imports_from_function,
)


@dataclass_json
@dataclass
class WorkerSpec:
    """
    Serializable specification of a QuantumWorker implementation.

    A WorkerSpec can be created from:
      - a Python file path
      - a Python module
      - a QuantumWorker class
      - an existing WorkerSpec
    """

    # Runtime class. Excluded from serialization.
    cls: Optional[type] = field(
        default=None,
        metadata=config(exclude=lambda _: True),
    )

    # Decorator arguments
    requirements: list[str] = field(default_factory=list)
    image: str = field(default="python:3.13")
    input_format: str = field(default="")
    output_format: str = field(default="")
    provider: str = field(default="")
    runtime_qall_version: str = field(default="")

    # Captured class information
    name: Optional[str] = None
    source: Optional[str] = None
    imports: dict[str, list[str]] = field(default_factory=dict)
    local_dependencies: dict[str, str] = field(default_factory=dict)

    def __init__(
        self,
        target: Path | str | type | ModuleType | WorkerSpec,
        name: Optional[str] = None,
        **kwargs: Any,
    ):
        self.cls = None
        self.requirements = []
        self.image = "python:3.13"
        self.input_format = ""
        self.output_format = ""
        self.provider = ""
        self.runtime_qall_version = importlib.metadata.version("qall")

        self.name = None
        self.source = None
        self.imports = {}
        self.local_dependencies = {}

        # Existing WorkerSpec
        if isinstance(target, WorkerSpec):
            self._copy_from(target)
            if name is not None:
                self.name = name
            return

        # QuantumWorker class
        if inspect.isclass(target):
            if not issubclass(target, QuantumWorker):
                raise TypeError(
                    f"WorkerSpec target must be a QuantumWorker subclass, "
                    f"got {target!r}."
                )

            self.name = name or target.__name__

            self._compile_from_class(target)
            return

        # Python module
        if isinstance(target, ModuleType):
            if not hasattr(target, "__file__") or target.__file__ is None:
                raise ValueError(
                    "Provided module does not have a physical __file__ attribute."
                )

            filepath = Path(target.__file__)
            self.name = name or target.__name__.split(".")[-1]

            self._compile_from_file(filepath, name=name, kwargs=kwargs)
            return

        # Python file
        if isinstance(target, (Path, str)):
            filepath = Path(target)

            if not filepath.exists():
                raise FileNotFoundError(f"Worker file does not exist: {filepath}")

            if filepath.suffix != ".py":
                raise ValueError(f"WorkerSpec target must be a Python file: {filepath}")

            self.name = name or filepath.stem

            self._compile_from_file(filepath, name=name, kwargs=kwargs)
            return

        raise TypeError(
            "WorkerSpec target must be a Path, str, module, "
            "QuantumWorker class, or WorkerSpec."
        )

    def _compile_from_file(
        self,
        filepath: Path,
        name: Optional[str],
        kwargs: dict[str, Any],
    ) -> None:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
        worker_cls = self._find_worker_class(tree)

        if worker_cls is None:
            raise ValueError(f"No QuantumWorker subclass found in {filepath}.")

        parent_dir = filepath.parent.resolve()
        pkg_name = f"__worker_pkg_{parent_dir.name}__"
        module_name = f"{pkg_name}.{filepath.stem}"

        # Simulated parent package to autorize relative imports
        pkg_mod = types.ModuleType(pkg_name)
        pkg_mod.__path__ = [str(parent_dir)]
        pkg_mod.__file__ = str(parent_dir / "__init__.py")
        sys.modules[pkg_name] = pkg_mod

        # Create child module attached to package
        fake_module = types.ModuleType(module_name)
        fake_module.__file__ = str(filepath.resolve())
        fake_module.__package__ = pkg_name

        module_globals = fake_module.__dict__
        module_globals["__file__"] = str(filepath.resolve())
        module_globals["__name__"] = module_name
        module_globals["__package__"] = pkg_name

        sys.modules[module_name] = fake_module
        sys.path.insert(0, str(parent_dir))

        # Statically discover the *project's* third-party imports so missing
        # packages do not crash compilation: they are stubbed during the exec
        # below and merged into the worker's requirements.
        discovered = discover_external_imports(filepath.parent)

        try:
            with lenient_imports(discovered):
                exec(compile(tree, str(filepath), "exec"), module_globals)

            decorated_spec = module_globals.get(worker_cls.class_name)
            if not isinstance(decorated_spec, WorkerSpec):
                raise RuntimeError(
                    f"Worker class {worker_cls.class_name!r} in {filepath} "
                    f"is not decorated with @quantum_worker."
                )

            self._copy_from(decorated_spec)
            # Auto-add the worker file's *global* third-party imports (mapped
            # to real package names); imports inside the worker's methods are
            # the user's explicit requirements responsibility.
            self.requirements = merge_requirements(
                self.requirements,
                map_imports_to_packages(discover_file_global_imports(filepath)),
            )
            clean_source = self._extract_class_source(
                source,
                worker_cls.class_name,
            )

            target_cls = decorated_spec.cls
            if target_cls and inspect.isclass(target_cls):
                self.cls = target_cls
                self.imports = _extract_imports_from_worker(target_cls)
                self.local_dependencies = _bundle_local_dependencies_from_worker(
                    target_cls
                )

                for name, val in module_globals.items():
                    if (
                        inspect.isfunction(val)
                        and val.__module__ == fake_module.__name__
                    ):
                        try:
                            self.local_dependencies[name] = textwrap.dedent(
                                inspect.getsource(val)
                            )
                        except (TypeError, OSError):
                            pass

            bundled_helpers = "\n\n".join(self.local_dependencies.values())
            if bundled_helpers:
                self.source = f"{bundled_helpers}\n\n{clean_source}".strip()
            else:
                self.source = clean_source

            self.name = name or self.name or filepath.stem
            self.requirements = sorted(set(self.requirements))
        finally:
            if str(parent_dir) in sys.path:
                sys.path.remove(str(parent_dir))

            sys.modules.pop(module_name, None)
            sys.modules.pop(pkg_name, None)

    def _compile_from_class(self, cls: type) -> None:
        if not issubclass(cls, QuantumWorker):
            raise TypeError(f"{cls.__name__} must inherit from QuantumWorker.")

        self.cls = cls
        self.name = cls.__name__

        metadata = getattr(cls, "__qall_worker_spec__", None)

        if metadata is None:
            raise ValueError(
                f"Worker {cls.__name__!r} is not decorated with " "@quantum_worker."
            )

        self.requirements = list(metadata.get("requirements", []))
        self.image = metadata.get("image", "python:3.13")
        self.input_format = normalize_circuit_type(metadata.get("input_format", ""))
        self.output_format = normalize_result_type(metadata.get("output_format", ""))
        self.provider = metadata.get("provider", "")

        try:
            self.source = textwrap.dedent(inspect.getsource(cls))
        except (TypeError, OSError):
            self.source = None

        self.imports = _extract_imports_from_worker(cls)
        self.local_dependencies = _bundle_local_dependencies_from_worker(cls)

    def _copy_from(self, other: WorkerSpec) -> None:
        self.cls = other.cls
        self.requirements = list(other.requirements)
        self.image = other.image
        self.input_format = other.input_format
        self.output_format = other.output_format
        self.provider = other.provider

        self.name = other.name
        self.source = other.source
        self.imports = dict(other.imports)
        self.local_dependencies = dict(other.local_dependencies)

    def _apply_kwargs(self, kwargs: dict[str, Any]) -> None:
        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise TypeError(f"Unknown WorkerSpec argument: {key}")

            setattr(self, key, value)

    def _find_worker_class(
        self,
        tree: ast.AST,
    ) -> Optional[_WorkerClassInfo]:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            for base in node.bases:
                if self._is_quantum_worker_base(base):
                    return _WorkerClassInfo(
                        class_name=node.name,
                    )

        return None

    @staticmethod
    def _is_quantum_worker_base(node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id == "QuantumWorker"

        if isinstance(node, ast.Attribute):
            return node.attr == "QuantumWorker"

        return False

    @staticmethod
    def _extract_class_source(
        source: str,
        class_name: str,
    ) -> str:
        tree = ast.parse(source)
        cleaned_body = []

        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                continue
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                node.decorator_list = [
                    dec
                    for dec in node.decorator_list
                    if not _is_quantum_worker_decorator(dec)
                ]
            cleaned_body.append(node)
        tree.body = cleaned_body
        return ast.unparse(tree)

    def _load_decorator_metadata(
        self,
        filepath: Path,
        cls: type,
    ) -> None:
        """
        Load WorkerSpec metadata from the @quantum_worker declaration.
        """
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            if node.name != cls.__name__:
                continue

            for decorator in node.decorator_list:
                if not _is_quantum_worker_decorator(decorator):
                    continue

                if not isinstance(decorator, ast.Call):
                    continue

                for keyword in decorator.keywords:
                    if keyword.arg is None:
                        continue

                    value = ast.literal_eval(keyword.value)

                    if not hasattr(self, keyword.arg):
                        raise TypeError(
                            f"Unknown @quantum_worker argument: " f"{keyword.arg}"
                        )

                    setattr(self, keyword.arg, value)

                return

        raise RuntimeError(
            f"Class {cls.__name__!r} is not decorated with " f"@quantum_worker."
        )


def _extract_imports_from_worker(cls: type) -> dict[str, list[str]]:
    """
    Extract imports used by a QuantumWorker class and its module-level helpers.
    """
    external_imports: set[str] = set()
    local_imports: set[str] = set()

    target_cls = cls.cls if isinstance(cls, WorkerSpec) else cls
    if not inspect.isclass(target_cls):
        return {"external_imports": [], "local_imports": []}

    # extract import from class method
    for _, member in inspect.getmembers(target_cls):
        if not (inspect.isfunction(member) or inspect.ismethod(member)):
            continue
        imports = _extract_imports_from_function(member)
        external_imports.update(imports["external_imports"])
        local_imports.update(imports["local_imports"])

    # extract import from module functions referend into the class
    module = sys.modules.get(target_cls.__module__)
    if module:
        for name, obj in inspect.getmembers(module):
            if inspect.isfunction(obj) and obj.__module__ == target_cls.__module__:
                imports = _extract_imports_from_function(obj)
                external_imports.update(imports["external_imports"])
                local_imports.update(imports["local_imports"])

    return {
        "external_imports": sorted(external_imports),
        "local_imports": sorted(local_imports),
    }


def _bundle_local_dependencies_from_worker(cls: type) -> dict[str, str]:
    """
    Recursively bundle local dependencies used by all methods of a worker,
    including top-level module functions and helpers.
    """
    bundled_code: dict[str, str] = {}
    visited: set[int] = set()

    target_cls = cls.cls if isinstance(cls, WorkerSpec) else cls
    if not inspect.isclass(target_cls):
        return {}

    # class methods
    for _, member in inspect.getmembers(target_cls):
        if not (inspect.isfunction(member) or inspect.ismethod(member)):
            continue

        dependencies = _bundle_local_dependencies(
            member,
            visited=visited,
        )
        bundled_code.update(dependencies)

    # global function in module
    module = sys.modules.get(target_cls.__module__)
    if module:
        for _, obj in inspect.getmembers(module):
            if inspect.isfunction(obj) and obj.__module__ == target_cls.__module__:
                if id(obj) not in visited:
                    dependencies = _bundle_local_dependencies(
                        obj,
                        visited=visited,
                    )
                    bundled_code.update(dependencies)

    return bundled_code


@dataclass(frozen=True)
class _WorkerClassInfo:
    class_name: str


def _is_quantum_worker_decorator(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "quantum_worker"

    if isinstance(node, ast.Call):
        return isinstance(node.func, ast.Name) and node.func.id == "quantum_worker"

    return False
