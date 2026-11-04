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

"""
Fail-loud guardrail that pins the pyan3 data model qall's call-graph builder
relies on (``qall/specification/utils.py`` → ``_build_call_graph_from_sources``).

If a future pyan3 release renames or reshapes ``from_sources``, ``visitor.nodes``,
``Node`` or ``Flavor``, these tests fail so the breakage shows up in CI as a clear
test failure instead of a silently empty call graph.
"""

import pytest

from pyan.analyzer import CallGraphVisitor, Flavor


def _build(*pairs):
    """Analyze ``(source, module_name)`` pairs via pyan's from_sources API."""
    return CallGraphVisitor.from_sources(list(pairs))


def test_from_sources_exists_and_processes_automatically():
    """from_sources runs the two-pass analysis; no extra ``process()`` needed."""
    visitor = _build(("def f():\n    return g()\n\ndef g():\n    return 1\n", "m"))
    assert any(node.name == "f" for bucket in visitor.nodes.values() for node in bucket)
    assert visitor.uses_edges  # populated without calling process() again
    # process() exists and is idempotent (safe if callers choose to invoke it).
    visitor.process()
    assert any(node.name == "f" for bucket in visitor.nodes.values() for node in bucket)


def test_node_shape_for_defined_function():
    visitor = _build(("def f(x):\n    return x + 1\n", "m"))
    (node,) = visitor.nodes["f"]
    assert node.name == "f"
    assert node.namespace == "m"
    assert node.defined is True
    assert node.flavor == Flavor.FUNCTION
    assert node.get_name() == "m.f"
    assert node.get_short_name() == "f"


def test_unknown_duplicate_nodes_have_none_namespace():
    """A forward-referenced name produces a `*.name` unknown node *in addition
    to* the real, defined `m.name` node. qall must use the qualified
    ``get_name()`` (``m.b``) as identity and never conflate the two."""
    visitor = _build(("def a():\n    return b()\n\ndef b():\n    return 1\n", "m"))
    # Real defined nodes carry a non-None namespace and are marked defined.
    for short in ("a", "b"):
        assert any(
            node.namespace == "m" and node.defined and node.flavor == Flavor.FUNCTION
            for bucket in visitor.nodes.values()
            for node in bucket
            if node.name == short
        )
    # The wildcard duplicate also exists (namespace None), proving the probe is
    # meaningful: short names alone are ambiguous, qualified names are not.
    unknown_names = {
        node.get_name()
        for bucket in visitor.nodes.values()
        for node in bucket
        if node.namespace is None
    }
    assert unknown_names  # there is at least one "*." bucket in a real analysis


def test_uses_edges_is_node_to_set_of_nodes():
    visitor = _build(("def a():\n    return b()\n\ndef b():\n    return 1\n", "m"))
    edges = {
        (src.get_name(), tgt.get_name())
        for src, targets in visitor.uses_edges.items()
        for tgt in targets
    }
    assert ("m.a", "m.b") in edges


def test_package_init_module_relative_import_resolves():
    """`<pkg>.__init__` naming lets relative imports resolve across modules."""
    visitor = _build(
        ("", "pkg.__init__"),
        (
            "from .sibling import helper\n\ndef run():\n    return helper()\n",
            "pkg.main",
        ),
        ("def helper():\n    return 42\n", "pkg.sibling"),
    )
    # The package's module node is named "pkg", not "pkg.__init__".
    module_names = {
        node.get_name()
        for bucket in visitor.nodes.values()
        for node in bucket
        if node.flavor == Flavor.MODULE
    }
    assert {"pkg", "pkg.main", "pkg.sibling"} <= module_names
    calls = {
        (src.get_name(), tgt.get_name())
        for src, targets in visitor.uses_edges.items()
        for tgt in targets
        if src.get_name() == "pkg.main.run"
    }
    assert ("pkg.main.run", "pkg.sibling.helper") in calls


def test_flavor_members_used_by_qall_exist():
    for expected in (
        Flavor.FUNCTION,
        Flavor.METHOD,
        Flavor.STATICMETHOD,
        Flavor.CLASSMETHOD,
        Flavor.CLASS,
    ):
        assert expected in Flavor
