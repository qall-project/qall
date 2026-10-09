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
import ast
import textwrap

from pathlib import Path
from typing import Optional

from qio.core.program import Program

from qall.object import (
    TaskNode,
    TaskPayload,
    TaskMetadata,
    TaskRunOutput,
)
from qall.registry import BlockRegistry
from qall.runtime import ArtifactBackend
from qall.runtime.subprocessor import run_task_in_subprocess
from qall.provider.workflow import resolve_qpu


class TaskRuntimeExecutor:
    def __init__(
        self,
        task_hash: str,
        registry: Path | str | BlockRegistry,
        artifact_backend: Optional[ArtifactBackend] = None,
        daemon_address: Optional[str] = None,
        worker_addresses: Optional[list[str]] = None,
    ):
        self.__block_registry = (
            BlockRegistry(registry, read_only=True)
            if isinstance(registry, (Path, str))
            else registry
        )
        self.__artifact_backend = artifact_backend
        self.__daemon_address = daemon_address
        self.__task_hash = task_hash
        self.__worker_addresses = worker_addresses

    def execute(
        self,
        task_run_id: str,
        input_artifact: Optional[bytes] = None,
        input_artifact_hash: Optional[str] = None,
    ) -> TaskRunOutput:
        if input_artifact is None and input_artifact_hash:
            if not self.__artifact_backend:
                raise RuntimeError(
                    "No artifact backend configured and no input_artifact provided"
                )
            input_artifact = self.__artifact_backend.download_artifact(
                input_artifact_hash
            )

        if input_artifact:
            print(
                f"[Executor] Input artifact for hash #{input_artifact_hash} loaded with size {len(input_artifact)}."
            )
        else:
            print("[Executor] No artifact loaded.")

        node: TaskNode = self.__block_registry.get_node_from_local(
            hash=self.__task_hash
        )

        if not node:
            raise ValueError(
                f"No Node found in local store for given task_hash: {self.__task_hash}"
            )

        print(f"[Executor] Node loaded: {node.hash}")

        payload: TaskPayload = self.__block_registry.get_payload_from_local(
            hash=node.payload_hash
        )

        if not payload:
            raise ValueError(
                f"No Payload associated with task {self.__task_hash} in local store."
            )

        metadata = TaskMetadata(**node.metadata)
        print(f"[Executor] Node's metadata and payload loaded: {metadata}")
        print("[Executor] Processing source...")
        source = _get_source(payload)

        try:
            parsed_ast = ast.parse(source)
        except SyntaxError:
            parsed_ast = None

        proxy_functions = []

        for child_name, child_hash in node.children.items():
            is_async = False

            if parsed_ast:

                class AsyncCallDetector(ast.NodeVisitor):
                    def __init__(self, target_name):
                        self.target_name = target_name
                        self.is_awaited = False

                    def visit_Await(self, ast_node):
                        if isinstance(ast_node.value, ast.Call):
                            func = ast_node.value.func
                            if (
                                isinstance(func, ast.Name)
                                and func.id == self.target_name
                            ):
                                self.is_awaited = True
                        self.generic_visit(ast_node)

                    def visit_AsyncFunctionDef(self, ast_node):
                        # Flag that we are inside an async function definition
                        self.is_async = True
                        # Continue traversing the child nodes (the body of the function)
                        self.generic_visit(ast_node)

                detector = AsyncCallDetector(child_name)
                detector.visit(parsed_ast)
                is_async = detector.is_awaited

            proxy_code = self._create_proxy_function(
                child_name=child_name,
                child_hash=child_hash,
                parent_task_id=task_run_id,
                is_async=is_async,
            )
            proxy_functions.append(proxy_code)

        if proxy_functions:
            source = "\n".join(proxy_functions) + "\n" + source

        print(f"[Executor] Built source:\n==========\n{source}\n==========")
        print("[Executor] Done processing source! Executing task...")

        task_result: dict = run_task_in_subprocess(
            source_code=source,
            entrypoint_name=metadata.name,
            input_artifact=input_artifact,
            worker_addresses=self.__worker_addresses,
        )

        output_artifact_hash = None
        output_artifact_bytes = None

        if task_result["return_code"] == 0 and task_result["return_value"]:
            output_artifact_bytes = task_result["return_value"]
            if self.__artifact_backend:
                output_artifact_hash = self.__artifact_backend.upload_artifact(
                    task_run_id=task_run_id,
                    artifact_bytes=output_artifact_bytes,
                )

        return TaskRunOutput(
            stdout=task_result["stdout"],
            stderr=task_result["stderr"],
            return_code=task_result["return_code"],
            output_artifact_hash=output_artifact_hash,
            output_artifact_bytes=output_artifact_bytes,
        )

    def _create_proxy_function(
        self,
        child_name: str,
        child_hash: str,
        parent_task_id: str,
        is_async: bool = False,
    ) -> str:
        """
        Generate the source code of a proxy that delegates execution to the Daemon.
        """
        func_def = "async def" if is_async else "def"
        async_import = "import asyncio" if is_async else ""

        if is_async:
            execution_call = f'await asyncio.to_thread(executor.execute_subtask, "{parent_task_id}", input_data)'
        else:
            execution_call = f'executor.execute_subtask("{parent_task_id}", input_data)'

        return textwrap.dedent(
            f"""
        {func_def} {child_name}(*args, **kwargs):
            {async_import}
            from qall.runtime import DaemonSubtaskExecutor
            from qall.registry import BlockRegistry
            import cloudpickle
            import os
            
            registry = BlockRegistry(local_root_dir="{self.__block_registry.local_root_dir}", read_only=True)
            daemon_address = os.environ.get("QALL_DAEMON_ADDRESS", "127.0.0.1:50053")
            executor = DaemonSubtaskExecutor(
                task_hash="{child_hash}",
                registry=registry,
                daemon_address=daemon_address
            )

            input_data = {{"args": args, "kwargs": kwargs}}

            result = {execution_call}

            executor.close()

            if result.return_code != 0:
                raise RuntimeError(f"Subtask '{child_name}' failed: {{result.stderr}}")
                
            return cloudpickle.loads(result.output_artifact_bytes)
        """
        )


### Helpers ###


def _get_source(payload: TaskPayload) -> str:
    if payload.code_format == "raw":
        return payload.code
    elif payload.code_format == "qio.program":
        program = Program.from_json_dict(payload.code)
        return program.to_python_source()
    else:
        raise NotImplementedError(f"Unknown code format '{payload.code_format}'")
