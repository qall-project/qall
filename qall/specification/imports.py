# Copyright 2026 Scaleway
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Utilities to compile qall specs without requiring third-party packages to be
installed in the *authoring* environment.

Third-party imports only need to be resolved when the task/worker actually runs
(in a container where ``piprequirements`` are installed). Building a
``WorkflowSpec``/``WorkerSpec`` (or deserializing a ``TaskSpec``) should never
crash on an import statement for a package that is not installed locally.

Two concerns live here:

- ``discover_external_imports`` statically walks a project directory
  (pipreqs-style, pure AST, no execution) and returns the set of third-party
  top-level module names it depends on.
- ``lenient_imports`` is a context manager that, while some user code is being
  executed for discovery purposes, replaces imports of those *missing*
  third-party modules with inert stubs instead of raising ``ModuleNotFoundError``.
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.abc
import importlib.machinery
import os
import re
import sys
import types

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

_STDLIB_NAMES = frozenset(sys.stdlib_module_names) | frozenset(sys.builtin_module_names)

_DEFAULT_IGNORE_PATTERNS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        "__pycache__",
        ".ipynb_checkpoints",
        "env",
        "venv",
        ".venv",
        "build",
        "dist",
        "node_modules",
        "*.egg-info",
    }
)


def discover_external_imports(
    project_root: Path | str,
    extra_ignore_dirs: Iterable[str] = (),
) -> set[str]:
    """
    Recursively scan ``project_root`` (pipreqs-style) and return the set of
    top-level third-party module names imported by any of its Python files.

    Local modules (anything whose name matches a file or directory inside the
    project) and standard-library modules are excluded. Nothing is executed:
    discovery is a pure AST pass, so it works whether or not the packages are
    installed.
    """
    ignore_patterns = _DEFAULT_IGNORE_PATTERNS | {
        os.path.basename(os.path.realpath(d)) for d in extra_ignore_dirs if d
    }

    candidates: set[str] = set()
    raw_imports: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(project_root, followlinks=False):
        dirnames[:] = [
            d
            for d in dirnames
            if not any(fnmatch.fnmatch(d, pattern) for pattern in ignore_patterns)
        ]
        candidates.add(os.path.basename(dirpath))

        for filename in filenames:
            if not filename.endswith((".py", ".pyw")):
                continue
            candidates.add(os.path.splitext(filename)[0])

            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    source = f.read()
            except OSError:
                continue

            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name:
                            raw_imports.add(alias.name.partition(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.level > 0 or not node.module:
                        continue
                    raw_imports.add(node.module.partition(".")[0])

    external: set[str] = set()
    for name in raw_imports:
        if name in candidates:
            continue
        if name in _STDLIB_NAMES:
            continue
        if name == "qall":
            continue
        external.add(name)

    return external


def external_import_module_names(import_statements: Iterable[str]) -> set[str]:
    """
    Extracts the top-level module names referenced by a list of import
    statements (as stored in ``TaskSpec.imports["external_imports"]``). Used to
    build the stub set when reconstructing a task from JSON.
    """
    names: set[str] = set()
    for statement in import_statements:
        try:
            tree = ast.parse(statement)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name:
                        names.add(alias.name.partition(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0 or not node.module:
                    continue
                names.add(node.module.partition(".")[0])
    return names


### Stub machinery ###


class _StubProxy:
    """Inert placeholder: any attribute access, call, index, iteration or basic
    arithmetic resolves back to itself, so discovery-time execution never
    crashes on a missing third-party package."""

    __slots__ = ()

    def __getattr__(self, name):
        return self

    def __call__(self, *args, **kwargs):
        return self

    def __getitem__(self, key):
        return self

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __bool__(self):
        return True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return id(self)

    def __repr__(self):
        return "<missing third-party module stub>"

    def __add__(self, other):
        return self

    def __radd__(self, other):
        return self

    def __sub__(self, other):
        return self

    def __rsub__(self, other):
        return self

    def __mul__(self, other):
        return self

    def __rmul__(self, other):
        return self

    def __truediv__(self, other):
        return self

    def __rtruediv__(self, other):
        return self

    def __neg__(self):
        return self

    def __pos__(self):
        return self

    def __abs__(self):
        return self


_STUB_PROXY = _StubProxy()


class _StubModule(types.ModuleType):
    """A module whose attributes resolve to the shared inert proxy.

    Dunder attributes (``__file__``, ``__path__``, ...) return ``None`` so
    introspection-based locality checks treat the stub as an external module
    rather than crashing on a proxy value.
    """

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            return None
        return _STUB_PROXY


class _StubLoader(importlib.abc.Loader):
    def create_module(self, spec) -> _StubModule:
        return _StubModule(spec.name)

    def exec_module(self, module) -> None:
        pass


class _LenientImportFinder(importlib.abc.MetaPathFinder):
    """Last-resort finder that stubs imports of missing third-party modules."""

    def __init__(self, stub_set: set[str], injected: set[str]):
        self._stub_set = stub_set
        self._injected = injected

    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".")[0]
        if top not in self._stub_set:
            return None

        existing = sys.modules.get(fullname)
        if existing is not None and not isinstance(existing, _StubModule):
            # Already imported for real (e.g. the top-level package exists).
            return None

        self._injected.add(fullname)
        return importlib.machinery.ModuleSpec(fullname, _StubLoader(), is_package=True)


@contextmanager
def lenient_imports(stub_set: Iterable[str]) -> Iterator[None]:
    """
    Context manager under which imports of missing *third-party* modules listed
    in ``stub_set`` resolve to inert stubs instead of raising.

    Only modules that fail every real finder are considered, so packages that
    are actually installed import normally. Stub modules injected into
    ``sys.modules`` are removed on exit so the environment is not polluted.
    """
    stub_set = {str(name) for name in stub_set if name}
    if not stub_set:
        yield
        return

    injected: set[str] = set()
    finder = _LenientImportFinder(stub_set, injected)
    sys.meta_path.append(finder)
    try:
        yield
    finally:
        try:
            sys.meta_path.remove(finder)
        except ValueError:
            pass
        for name in injected:
            sys.modules.pop(name, None)
            for sub in [
                module_name
                for module_name in sys.modules
                if module_name.startswith(name + ".")
            ]:
                sys.modules.pop(sub, None)


### piprequirements merging ###

_SPEC_SEPARATORS_RE = re.compile(r"[<>=~!\[\];,\s]+")


def _bare_package_name(requirement: str) -> str:
    """Extracts the normalized bare package name from a requirement spec."""
    return _SPEC_SEPARATORS_RE.split(requirement, 1)[0].strip().lower()


def merge_requirements(
    explicit: list[str],
    discovered: Iterable[str],
) -> list[str]:
    """
    Merges auto-discovered third-party package names into an explicit
    ``piprequirements`` list.

    Explicit entries are kept verbatim (including any version/extras spec);
    discovered names that are not already covered are appended as bare package
    names.
    """
    result = list(explicit)
    seen = {_bare_package_name(requirement) for requirement in result}
    for package in sorted({str(name).strip() for name in discovered if name}):
        bare = package.lower()
        if bare not in seen:
            result.append(package)
            seen.add(bare)
    return result
