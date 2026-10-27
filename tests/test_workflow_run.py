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
Unit tests for the end-of-run QoL artifact hints in ``qall.core.workflow_run``:
the ``-> `qall artifact show <hash>``` lines emitted after a successful local
workflow run, annotated with the entrypoint task that produced the artifacts.
"""

from types import SimpleNamespace

from qall.core.workflow_run import _artifact_show_hints, _producing_task_name
from qall.object import TaskDag, TaskMetadata, TaskNode


def _node(name: str) -> TaskNode:
    """A TaskNode shaped like the ones BlockRegistry builds (dict metadata)."""
    return TaskNode(
        payload_hash=f"payload-{name}",
        resources={},
        children={},
        metadata={"name": name},
    )


def test_producing_task_name_resolves_root_node_from_dict_metadata():
    nodes = [_node("task_a"), _node("main")]
    dag = TaskDag(nodes=nodes, payloads=[], root_hash=nodes[1].hash)

    assert _producing_task_name(dag) == "main"


def test_producing_task_name_handles_metadata_object():
    node = TaskNode(
        payload_hash="payload-x",
        resources={},
        children={},
        metadata=TaskMetadata(name="obj_task"),
    )
    dag = TaskDag(nodes=[node], payloads=[], root_hash=node.hash)

    assert _producing_task_name(dag) == "obj_task"


def test_producing_task_name_is_none_when_unresolvable():
    assert _producing_task_name(None) is None

    node = _node("loner")
    dag_without_match = TaskDag(nodes=[node], payloads=[], root_hash="not-here")
    assert _producing_task_name(dag_without_match) is None

    unnamed = TaskNode(
        payload_hash="payload-x",
        resources={},
        children={},
        metadata={},
    )
    dag_unnamed = TaskDag(nodes=[unnamed], payloads=[], root_hash=unnamed.hash)
    assert _producing_task_name(dag_unnamed) is None


def test_artifact_show_hints_emit_runable_commands():
    artifacts = [SimpleNamespace(hash="aaa111"), SimpleNamespace(hash="bbb222")]

    hints = _artifact_show_hints(artifacts, producing_task="main")

    assert hints.splitlines() == [
        "-> `qall artifact show aaa111` (from task: main)",
        "-> `qall artifact show bbb222` (from task: main)",
    ]


def test_artifact_show_hints_without_task_name():
    hints = _artifact_show_hints([SimpleNamespace(hash="abc")])

    assert hints == "-> `qall artifact show abc`"


def test_artifact_show_hints_skips_hashless_and_empty_inputs():
    artifacts = [SimpleNamespace(name="no-hash"), SimpleNamespace(hash="ok")]

    assert _artifact_show_hints(artifacts, producing_task="main") == (
        "-> `qall artifact show ok` (from task: main)"
    )
    assert _artifact_show_hints([]) == ""
    assert _artifact_show_hints(None) == ""
