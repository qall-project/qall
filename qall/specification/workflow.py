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
import asyncio
import json
import lzma
import cloudpickle
import inspect
import concurrent.futures

import rustworkx as rx

from matplotlib import pyplot as plt
from pathlib import Path
from rustworkx.visualization import mpl_draw
from types import ModuleType
from typing import Optional, overload

from .task import TaskSpec, _inject_referenced_tasks
from .utils import generate_call_graph


class WorkflowSpec:

    def __init__(
        self, target: Path | str | TaskSpec | ModuleType, name: Optional[str] = None
    ):
        """
        Initializes a WorkflowSpec framework context.
        """
        self._entrypoint_task: TaskSpec = None
        self.tasks: dict[str, TaskSpec] = {}
        self._qualified_tasks: dict[tuple[str | None, str], TaskSpec] = {}

        # Register this instance inside Task context during static initialization phase
        TaskSpec.compilation(self)

        try:
            # Resolve the filepath and name from the polymorphic target
            if isinstance(target, TaskSpec):
                if not getattr(target, "entrypoint", False):
                    raise ValueError(
                        f"TaskSpec '{target.name}' passed to Workflow must have entrypoint=True"
                    )
                # Extract the file where the task function was defined
                filepath = Path(inspect.getfile(target.func))
                self.name = name or target.name
                self._entrypoint_task = target

            elif isinstance(target, ModuleType):
                if not hasattr(target, "__file__"):
                    raise ValueError(
                        "Provided module does not have a physical __file__ attribute."
                    )
                filepath = Path(target.__file__)
                self.name = name or target.__name__.split(".")[-1]

            elif isinstance(target, (Path, str)):
                filepath = Path(target)
                self.name = name or filepath.stem

            else:
                raise TypeError(
                    "Workflow target must be a Path, str, ModuleType, or TaskSpec."
                )

            self.graph = generate_call_graph(filepath, "rxgraph")

            # Fallback tracking if target was a file path and entrypoint wasn't predefined
            if self._entrypoint_task is None:
                for registered_task in self.tasks.values():
                    if registered_task.entrypoint:
                        self._entrypoint_task = registered_task
                        break
        finally:
            # FIXED: Calling reset clears global tracking contexts preventing
            # leakage across sequential tests, even when graph building raises.
            TaskSpec.reset()

    @property
    def task_registry(self) -> dict[str, TaskSpec]:
        """Legacy property alias targeting the updated tasks registry."""
        return self.tasks

    @task_registry.setter
    def task_registry(self, value: dict[str, TaskSpec]):
        self.tasks = value

    @staticmethod
    def _qualified_key(task: TaskSpec) -> tuple[str | None, str]:
        """
        Stable identity for a task within a workflow: ``(defining module, name)``.

        The module is only known while the task holds its live function (i.e.
        during compilation); once a task is rebuilt from JSON the module is not
        persisted, so the key gracefully degrades to ``(None, name)``. Collision
        detection therefore operates where it matters (compile time) without
        inventing false positives after deserialization.
        """
        module = getattr(getattr(task, "func", None), "__module__", None)
        return (module, task.name)

    def declare_task(self, task: TaskSpec):
        # FIXED: Allow overwriting during COMPILATION mode to tolerate dual file
        # executions of test loaders.
        if task.name in self.tasks:
            previous = self.tasks[task.name]
            if previous is not task:
                prev_key = self._qualified_key(previous)
                new_key = self._qualified_key(task)
                # Genuine collision: two distinct tasks share a short name but are
                # defined in different modules. Surface it instead of silently
                # overwriting one with the other in the graph.
                if (
                    prev_key[0] is not None
                    and new_key[0] is not None
                    and prev_key[0] != new_key[0]
                ):
                    raise ValueError(
                        f"Task name collision: {task.name!r} is defined in both "
                        f"module {prev_key[0]!r} and {new_key[0]!r}. "
                        "Rename one of the tasks to disambiguate them."
                    )
                if TaskSpec._mode != "COMPILATION":
                    raise ValueError(f"Task {task.name} already declared")
        self.tasks[task.name] = task
        self._qualified_tasks[self._qualified_key(task)] = task
        return True

    @property
    def entrypoint_task(self) -> TaskSpec:
        return self._entrypoint_task

    @entrypoint_task.setter
    def entrypoint_task(self, value: TaskSpec):
        # FIXED: Tolerate re-assignment if names match during re-execution phases of compilation
        if (
            self._entrypoint_task is not None
            and self._entrypoint_task.name != value.name
        ):
            raise ValueError("Entrypoint task already set")
        self._entrypoint_task = value
        return self._entrypoint_task

    def __call__(self, *args, **kwargs):
        if not self.entrypoint_task:
            raise RuntimeError("Cannot execute Workflow: No entrypoint task defined.")

        if inspect.iscoroutinefunction(self.entrypoint_task.func):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # No event loop is currently running: safe to create a fresh one.
                return asyncio.run(self.entrypoint_task.func(*args, **kwargs))
            else:
                # A loop is already running: execute the coroutine in a worker
                # thread with its own event loop to avoid re-entrancy issues.
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        lambda: asyncio.run(self.entrypoint_task.func(*args, **kwargs))
                    )
                    return future.result()
        else:
            return self.entrypoint_task.func(*args, **kwargs)

    @overload
    def __contains__(self, task: TaskSpec) -> bool: ...
    @overload
    def __contains__(self, task_name: str) -> bool: ...
    def __contains__(self, element: TaskSpec | str) -> bool:
        if isinstance(element, TaskSpec):
            return element in self.tasks.values()
        elif isinstance(element, str):
            return element in self.tasks.keys()
        raise TypeError("Invalid type for membership test")

    def dumps(self) -> bytes:
        return cloudpickle.dumps(self)

    @classmethod
    def loads(cls, data: bytes) -> "WorkflowSpec":
        return cloudpickle.loads(data)

    def to_json(self, indent: int = 4) -> str:
        workflow_state = {
            "name": self.name,
            "tasks": {name: task.to_dict() for name, task in self.tasks.items()},
            "graph_json": None,
        }

        # rx.node_link_json expects nodes/edges to be convertible to dict[str, str].
        # Since nodes are strings (task names), we wrap them in a dict.
        # We also json.dumps() the edge data to safely bypass rustworkx type constraints.
        if self.graph is not None:
            rx_json_str = rx.node_link_json(
                self.graph,
                node_attrs=lambda node_name: {"name": node_name},
                edge_attrs=lambda edge_data: {"payload": json.dumps(edge_data)},
            )

            # Parse it back to a Python dict so it embeds as a clean, structured object
            # in the final JSON, rather than an ugly escaped string block.
            workflow_state["graph_json"] = json.loads(rx_json_str)

        return json.dumps(workflow_state, indent=indent)

    def to_file(self, path: Path | str, compression: bool = False) -> None:
        """
        Serializes the Workflow and saves it to a file.

        Args:
            path: The destination file path.
            compression: If True, compresses the JSON payload using LZMA at the maximum ratio.
        """
        path = Path(path)
        json_str = self.to_json(indent=4)

        if compression:
            # preset=9 forces the highest compression ratio possible in the LZMA algorithm
            compressed_data = lzma.compress(json_str.encode("utf-8"), preset=9)
            path.write_bytes(compressed_data)
        else:
            path.write_text(json_str, encoding="utf-8")

    @classmethod
    def from_file(cls, path: Path | str) -> "WorkflowSpec":
        """
        Reads a file and deserializes it into a Workflow instance.
        Automatically detects and decompresses LZMA payloads.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Cannot load Workflow. File not found: {path}")

        raw_bytes = path.read_bytes()
        if raw_bytes.startswith(b"\xfd7zXZ\x00"):
            json_str = lzma.decompress(raw_bytes).decode("utf-8")
        else:
            json_str = raw_bytes.decode("utf-8")

        return cls.from_json(json_str)

    @classmethod
    def from_json(cls, json_str: str) -> "WorkflowSpec":
        state = json.loads(json_str)

        instance = cls.__new__(cls)
        instance.name = state["name"]
        instance.tasks = {}
        instance._entrypoint_task = None
        instance._qualified_tasks = {}

        TaskSpec.reset()
        TaskSpec._parent_workflow = instance

        for task_dict in state.get("tasks", {}).values():
            TaskSpec.from_dict(task_dict)

        if state.get("graph_json"):
            rx_json_str = json.dumps(state["graph_json"])
            instance.graph = rx.parse_node_link_json(
                rx_json_str,
                node_attrs=lambda attr: attr["name"],
                edge_attrs=lambda attr: (
                    json.loads(attr["payload"]) if "payload" in attr else {}
                ),
            )
        else:
            instance.graph = rx.PyDiGraph()

        # Once every task has been reconstructed, wire up cross-task references
        # (e.g. a task calling another task) inside the reconstructed callables.
        instance._resolve_cross_task_references()

        TaskSpec.reset()
        return instance

    def _resolve_cross_task_references(self) -> None:
        """
        Injects the reconstructed callable of every referenced task into the
        namespace of the tasks (and their bundled dependencies) that call them.
        Called after all tasks have been rebuilt from JSON so that forward
        references resolve regardless of serialization order.
        """
        for task in self.tasks.values():
            if task.func is None:
                continue
            _inject_referenced_tasks(task.func.__globals__, self.tasks)

    def draw(self):
        if self.graph is None:
            print("Graph is not constructed yet. Build the workflow first.")
            return

        pos = rx.spring_layout(self.graph)

        plt.ion()
        plt.figure(figsize=(14, 10))

        nodes: list[str] = list(self.graph.nodes())
        nodes_colors = ["#ADD8E6"] * len(nodes)

        if self.entrypoint_task and self.entrypoint_task.name in nodes:
            entrypoint_id = nodes.index(self.entrypoint_task.name)
            nodes_colors[entrypoint_id] = "#F66D19"

        mpl_draw(
            self.graph,
            pos=pos,
            with_labels=True,
            labels=lambda node_data: node_data,
            edge_labels=lambda _: "calls",
            node_color=nodes_colors,
            node_size=3000,
            font_size=10,
            arrow_size=20,
        )

        plt.title(f"Workflow DAG", fontsize=14, fontweight="bold")
        plt.axis("off")
        plt.show(block=True)
