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
import textwrap
import pytest

from pathlib import Path

from qall.object import Tag
from qall.registry import BlockRegistry
from qall.specification import WorkflowSpec
from qall.specification.run_analyzer import _RunAnalyzer


def _compile_and_push(
    registry: BlockRegistry,
    tmp_path: Path,
    filename: str,
    code: str,
    tag_name: str,
    version: str = "v1",
):
    """Writes a workflow file, compiles its WorkflowSpec, and pushes its TaskDag."""
    wf_file = tmp_path / filename
    wf_file.write_text(textwrap.dedent(code), encoding="utf-8")
    spec = WorkflowSpec(wf_file)
    dag = registry.create_workflow_dag(spec)
    registry.push(tag=Tag(name=tag_name, version=version), dag=dag)
    return spec, dag


class TestStaticRunAnalysis:
    """Validates static AST classification of external_runs vs quantum_runs."""

    def test_extracts_static_external_runs_without_polluting_quantum_runs(self):
        source = textwrap.dedent(
            """
            import qall
            from qall import run as qrun

            def my_task(x):
                wf_ref = "qaoa:v1"
                a = qall.run(wf_ref, x)
                b = qrun("bafyreib2externalhash", a, scale=2)
                c = qall.run(target="postproc:v2", data=b)
                return c
        """
        )
        res = _RunAnalyzer(source, task_name="my_task").analyze()

        assert res.external_runs == ["qaoa:v1", "bafyreib2externalhash", "postproc:v2"]
        assert res.quantum_runs == []

    def test_extracts_external_runs_from_local_helper_functions(self, tmp_path: Path):
        wf_file = tmp_path / "helper_wf.py"
        wf_file.write_text(
            textwrap.dedent(
                """
            import qall

            def call_sub(val):
                return qall.run("sub_wf:v1", val)

            @qall.workflow()
            def main():
                return call_sub(10)
        """
            ),
            encoding="utf-8",
        )
        spec = WorkflowSpec(wf_file)
        assert spec.entrypoint_task.external_runs == ["sub_wf:v1"]
        assert spec.entrypoint_task.quantum_runs == []

    @pytest.mark.parametrize(
        "bad_body",
        [
            'qall.run("", 1)',
            'ver = "v1"\nqall.run(f"qaoa:{ver}", 1)',
            'ver = "v1"\nqall.run("qaoa:" + ver, 1)',
            "def fn(target: str):\n    return qall.run(target, 1)",
            'ref = "a:v1"\nref = "b:v1"\nqall.run(ref, 1)',
        ],
    )
    def test_rejects_dynamic_or_empty_workflow_references(self, bad_body: str):
        source = (
            f"import qall\n\ndef bad_task():\n{textwrap.indent(bad_body, '    ')}\n"
        )
        with pytest.raises(ValueError):
            _RunAnalyzer(source, task_name="bad_task").analyze()


class TestMerkleDagComposition:
    """Validates DAG topology and cryptographic hash invariance across compositions."""

    def test_workflow_a_calls_standalone_task_by_hash(self, tmp_path: Path):
        registry = BlockRegistry(tmp_path / "registry")

        # 1. Push a standalone task (via a single-task workflow) and capture its root node hash
        _, task_dag = _compile_and_push(
            registry,
            tmp_path,
            "standalone_task.py",
            """
            import qall

            @qall.workflow()
            def compute(x):
                return x * 3
            """,
            tag_name="standalone_compute",
        )
        target_task_hash = task_dag.root_hash
        original_target_node = registry.get_node_from_local(target_task_hash)

        # 2. Workflow A references the task directly by its raw hash
        _, dag_a = _compile_and_push(
            registry,
            tmp_path,
            "wf_a.py",
            f"""
            import qall

            @qall.task()
            def step_a():
                return 7

            @qall.workflow()
            def main():
                v = step_a()
                return qall.run("{target_task_hash}", v)
            """,
            tag_name="wf_a",
        )

        root_a = registry.get_node_from_local(dag_a.root_hash)
        assert root_a.children[target_task_hash] == target_task_hash
        assert "step_a" in root_a.children

        # Verify target task node and hash remain completely unchanged
        assert registry.get_node_from_local(target_task_hash) == original_target_node

    def test_workflow_a_calls_workflow_b(self, tmp_path: Path):
        registry = BlockRegistry(tmp_path / "registry")

        # 1. Workflow B with internal subtask
        _, dag_b = _compile_and_push(
            registry,
            tmp_path,
            "wf_b.py",
            """
            import qall

            @qall.task()
            def helper_b(x):
                return x + 5

            @qall.workflow()
            def main(x):
                return helper_b(x) * 2
            """,
            tag_name="wf_b",
        )
        node_b_before = registry.get_node_from_local(dag_b.root_hash)
        helper_b_hash = node_b_before.children["helper_b"]

        # 2. Workflow A (also defines a `main` entrypoint — no name collision!)
        _, dag_a = _compile_and_push(
            registry,
            tmp_path,
            "wf_a.py",
            """
            import qall

            @qall.workflow()
            def main():
                return qall.run("wf_b:v1", 10)
            """,
            tag_name="wf_a",
        )

        node_a = registry.get_node_from_local(dag_a.root_hash)
        assert node_a.children == {"wf_b:v1": dag_b.root_hash}

        # Verify Workflow B's root hash and internal child hashes are untouched
        node_b_after = registry.get_node_from_local(dag_b.root_hash)
        assert node_b_after.hash == dag_b.root_hash
        assert node_b_after.children == {"helper_b": helper_b_hash}
        assert {n.hash for n in dag_a.nodes} >= {
            dag_a.root_hash,
            dag_b.root_hash,
            helper_b_hash,
        }

    def test_transitive_chain_a_calls_b_calls_c(self, tmp_path: Path):
        registry = BlockRegistry(tmp_path / "registry")

        # 1. Workflow C
        _, dag_c = _compile_and_push(
            registry,
            tmp_path,
            "wf_c.py",
            """
            import qall

            @qall.workflow()
            def main(x):
                return x + 1
            """,
            tag_name="wf_c",
        )

        # 2. Workflow B -> C
        _, dag_b = _compile_and_push(
            registry,
            tmp_path,
            "wf_b.py",
            """
            import qall

            @qall.workflow()
            def main(x):
                return qall.run("wf_c:v1", x) * 10
            """,
            tag_name="wf_b",
        )

        # 3. Workflow A -> B
        _, dag_a = _compile_and_push(
            registry,
            tmp_path,
            "wf_a.py",
            """
            import qall

            @qall.workflow()
            def main():
                return qall.run("wf_b:v1", 4)
            """,
            tag_name="wf_a",
        )

        node_a = registry.get_node_from_local(dag_a.root_hash)
        node_b = registry.get_node_from_local(dag_b.root_hash)
        node_c = registry.get_node_from_local(dag_c.root_hash)

        assert node_a.children == {"wf_b:v1": dag_b.root_hash}
        assert node_b.children == {"wf_c:v1": dag_c.root_hash}
        assert node_c.children == {}

        # All transitive nodes must be present in dag_a for resource/dataloader resolution
        dag_a_hashes = {n.hash for n in dag_a.nodes}
        assert {dag_a.root_hash, dag_b.root_hash, dag_c.root_hash}.issubset(
            dag_a_hashes
        )

    def test_diamond_composition_a_calls_b_and_c_and_b_calls_c(self, tmp_path: Path):
        registry = BlockRegistry(tmp_path / "registry")

        # 1. Shared Workflow C
        _, dag_c = _compile_and_push(
            registry,
            tmp_path,
            "wf_c.py",
            """
            import qall

            @qall.workflow()
            def main(x):
                return x * 2
            """,
            tag_name="wf_c",
        )

        # 2. Workflow B -> C
        _, dag_b = _compile_and_push(
            registry,
            tmp_path,
            "wf_b.py",
            """
            import qall

            @qall.workflow()
            def main(x):
                return qall.run("wf_c:v1", x) + 3
            """,
            tag_name="wf_b",
        )

        # 3. Workflow A -> B and A -> C
        _, dag_a = _compile_and_push(
            registry,
            tmp_path,
            "wf_a.py",
            """
            import qall

            @qall.workflow()
            def main(x):
                from_b = qall.run("wf_b:v1", x)
                from_c = qall.run("wf_c:v1", x)
                return from_b + from_c
            """,
            tag_name="wf_a",
        )

        node_a = registry.get_node_from_local(dag_a.root_hash)
        node_b = registry.get_node_from_local(dag_b.root_hash)

        # Both A and B point to the exact same immutable hash for C
        assert node_a.children["wf_b:v1"] == dag_b.root_hash
        assert node_a.children["wf_c:v1"] == dag_c.root_hash
        assert node_b.children["wf_c:v1"] == dag_c.root_hash

        # No duplicate TaskNode entries in dag_a.nodes
        node_hashes = [n.hash for n in dag_a.nodes]
        assert len(node_hashes) == len(set(node_hashes))
        assert set(node_hashes) == {dag_a.root_hash, dag_b.root_hash, dag_c.root_hash}
