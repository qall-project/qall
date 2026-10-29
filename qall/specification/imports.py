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

Several concerns live here:

- ``discover_external_imports`` statically walks a project directory
  (pipreqs-style, pure AST, no execution) and returns the set of third-party
  top-level module names it depends on. It is used to build the stub set so
  compilation never crashes on missing packages.
- ``discover_file_global_imports`` parses a *single* workflow/worker file and
  returns only its **global** (module-body scope) third-party module names.
  Task-scope imports (inside task bodies) and sibling files are excluded.
- ``map_imports_to_packages`` maps those discovered *module* names to the pip
  *package* names that provide them (``cv2`` -> ``opencv-python``). Auto-added
  ``piprequirements`` entries always carry real package names.
- ``lenient_imports`` is a context manager that, while some user code is being
  executed for discovery purposes, replaces imports of those *missing*
  third-party modules with inert stubs instead of raising ``ModuleNotFoundError``.
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.abc
import importlib.machinery
import importlib.metadata
import logging
import os
import re
import sys
import types

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

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

    # A virtualenv may be nested inside the project directory. Its files are installed packages, not
    # project code, so skip venv roots (any name, detected via pyvenv.cfg) and
    # site-packages / dist-packages directories entirely; otherwise this walk
    # would scan thousands of third-party files and pollute the discovered set.
    for dirpath, dirnames, filenames in os.walk(project_root, followlinks=False):
        retained_dirs = []
        for d in dirnames:
            if any(fnmatch.fnmatch(d, pattern) for pattern in ignore_patterns):
                continue
            full = os.path.join(dirpath, d)
            if d in ("site-packages", "dist-packages"):
                continue
            if os.path.isfile(os.path.join(full, "pyvenv.cfg")):
                continue
            retained_dirs.append(d)
        dirnames[:] = retained_dirs

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


def _is_main_guard(node: ast.stmt) -> bool:
    """True for a top-level ``if __name__ == '__main__':`` guard statement."""
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    left = node.test.left
    return isinstance(left, ast.Name) and left.id == "__name__"


def _global_import_nodes(nodes: Iterable[ast.stmt]) -> list[ast.stmt]:
    """
    Collects the import statements that live at *global* scope from an iterable
    of module-body statements.

    Only direct children of the module body count, plus imports nested in
    top-level ``try``/``except`` blocks and ``if __name__ == '__main__':``
    guards. Imports inside function/class bodies (task-scope) are deliberately
    **not** collected: they are the user's per-task ``piprequirements``
    responsibility.
    """
    found: list[ast.stmt] = []
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append(node)
        elif isinstance(node, ast.Try):
            for group in (node.body, node.orelse, node.finalbody):
                found.extend(_global_import_nodes(group))
            for handler in node.handlers:
                found.extend(_global_import_nodes(handler.body))
        elif _is_main_guard(node):
            found.extend(_global_import_nodes(node.body))
            found.extend(_global_import_nodes(node.orelse))
    return found


def discover_file_global_imports(filepath: Path | str) -> set[str]:
    """
    Returns the set of top-level *third-party* module names imported at the
    **global** scope of a single workflow/worker file.

    Standard-library modules, the ``qall`` task library and immediate sibling
    local modules are excluded. Unlike ``discover_external_imports`` this does
    not walk the whole project directory, so unrelated sibling files do not
    pollute the result, and task-scope imports (inside task bodies) are not
    considered.
    """
    path = Path(filepath)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return set()

    # Immediate sibling files/dirs are treated as local modules, e.g. an
    # `import utils_helper` next to the workflow file must not become a package.
    candidates: set[str] = set()
    try:
        for entry in path.parent.iterdir():
            candidates.add(entry.stem if entry.is_file() else entry.name)
    except OSError:
        pass

    raw: set[str] = set()
    for node in _global_import_nodes(tree.body):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    raw.add(alias.name.partition(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0 or not node.module:
                continue
            raw.add(node.module.partition(".")[0])

    external: set[str] = set()
    for name in raw:
        if name in candidates:
            continue
        if name in _STDLIB_NAMES:
            continue
        if name == "qall":
            continue
        external.add(name)

    return external


# Common modules whose import name differs from the pip package that provides
# them. Used as a fallback when the package is not installed locally (and
# therefore absent from importlib.metadata.packages_distributions()).
_IMPORT_PACKAGE_ALIASES: dict[str, str] = {
    "bs4": "beautifulsoup4",
    "cbor": "cbor2",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "docx": "python-docx",
    "dotenv": "python-dotenv",
    "fitz": "pymupdf",
    "gi": "pygobject",
    "googleapiclient": "google-api-python-client",
    "grpc": "grpcio",
    "jwt": "pyjwt",
    "merlin": "merlinquantum",
    "nacl": "pynacl",
    "OpenSSL": "pyopenssl",
    "PIL": "pillow",
    "pkg_resources": "setuptools",
    "psycopg2": "psycopg2-binary",
    "qsimcirq": "qsimcirq",
    "qiskit_aer": "qiskit-aer",
    "serial": "pyserial",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}


def _casefold_get(mapping: dict[str, list[str]], key: str) -> list[str]:
    """Case-insensitive ``dict.get`` for packages_distributions-style maps."""
    value = mapping.get(key)
    if value:
        return value
    lowered = key.lower()
    for existing, dists in mapping.items():
        if existing.lower() == lowered:
            return dists
    return []


def map_imports_to_packages(module_names: Iterable[str]) -> set[str]:
    """
    Maps top-level third-party *module* names to the pip *package* names that
    provide them, so auto-detected ``piprequirements`` entries are always
    installable (e.g. ``cv2`` -> ``opencv-python``, ``PIL`` -> ``pillow``).

    Resolution order:

    1. ``importlib.metadata.packages_distributions()`` — authoritative for
       packages installed in the current environment. A module provided by
       exactly one distribution maps to that package; a namespace provided by
       several distributions (e.g. ``google``) is ambiguous, so a warning is
       logged and the module name is kept as-is.
    2. The curated ``_IMPORT_PACKAGE_ALIASES`` table, for common modules whose
       name differs from their package.

    Names that cannot be mapped confidently are logged with a warning and kept
    unchanged (best-effort: most import names already match their package name).
    """
    if not module_names:
        return set()

    try:
        dist_by_module = importlib.metadata.packages_distributions()
    except Exception:  # pragma: no cover - importlib.metadata is very stable
        dist_by_module = {}

    packages: set[str] = set()
    for name in {str(n).strip() for n in module_names if n}:
        dists = _casefold_get(dist_by_module, name)
        if dists:
            if len(dists) == 1:
                packages.add(dists[0])
                continue
            logger.warning(
                "Import %r is provided by multiple installed distributions "
                "(%s); keeping it as-is.",
                name,
                ", ".join(sorted(dists)),
            )
            packages.add(name)
            continue

        package = _IMPORT_PACKAGE_ALIASES.get(name) or _IMPORT_PACKAGE_ALIASES.get(
            name.lower()
        )
        if package:
            packages.add(package)
            continue

        logger.warning(
            "Could not map import %r to a pip package name; keeping it as-is.",
            name,
        )
        packages.add(name)

    return packages


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
