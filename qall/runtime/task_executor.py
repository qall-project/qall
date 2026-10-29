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
    TaskRunOutput,
)
from qall.registry import BlockRegistry
from qall.runtime import ArtifactBackend
from qall.runtime.subprocessor import run_task_in_subprocess
from qall.config.dataloader import (
    dataloader_secrets_path,
    read_dataloader_secrets,
    write_dataloader_secrets,
)


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

        metadata = node.metadata
        print(f"[Executor] Node's metadata and payload loaded: {metadata}")
        print("[Executor] Processing source...")
        source = _get_source(payload)

        dataloaders_file = None
        dataloaders_provisioned = False
        if metadata.dataloaders:
            dataloaders_file, dataloaders_provisioned = self._prepare_dataloaders_file(
                metadata.dataloaders
            )
            print(
                f"[Executor] Resolved dataloader(s) {metadata.dataloaders} "
                f"(secrets at {dataloaders_file})."
            )

        proxy_functions = []

        for child_name, child_hash in node.children.items():
            is_async = _child_task_is_async(
                registry=self.__block_registry,
                child_hash=child_hash,
                child_name=child_name,
            )

            proxy_code = self._create_proxy_function(
                child_name=child_name,
                child_hash=child_hash,
                parent_task_id=task_run_id,
                is_async=is_async,
                worker_addresses=self.__worker_addresses,
            )
            proxy_functions.append(proxy_code)

        if proxy_functions:
            source = "\n".join(proxy_functions) + "\n" + source

        print(f"[Executor] Built source:\n==========\n{source}\n==========")
        print("[Executor] Done processing source! Executing task...")

        try:
            task_result: dict = run_task_in_subprocess(
                source_code=source,
                entrypoint_name=metadata.name,
                input_artifact=input_artifact,
                worker_addresses=self.__worker_addresses,
                dataloaders_file=str(dataloaders_file) if dataloaders_file else None,
            )
        finally:
            # In the daemonless path the executor provisioned the secrets file
            # itself; remove it so nothing sensitive lingers after the run. In
            # the daemon path the file was provisioned by the host client,
            # which is responsible for cleaning it up.
            if dataloaders_file and dataloaders_provisioned:
                dataloaders_file.unlink(missing_ok=True)

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

    def _prepare_dataloaders_file(
        self, names: list[str]
    ) -> tuple[Optional[Path], bool]:
        """
        Ensures the resolved-secrets file for this task exists at the
        conventioned ``/dev/shm/qall-dataloaders/<task_hash>.json`` mount path
        and returns ``(path, provisioned_here)``.

        In the daemon/container path the file was already provisioned by the
        host client (``provisioned_here`` is ``False``). In the daemonless path
        it is resolved from the local config + keyring and written here so the
        subprocess reads it uniformly. Raises ``ValueError`` when a referenced
        dataloader is not defined.
        """
        path = dataloader_secrets_path(self.__task_hash)
        secrets = read_dataloader_secrets(self.__task_hash)
        if secrets is None:
            from qall.core.dataloader import resolve_dataloader_specs

            write_dataloader_secrets(self.__task_hash, resolve_dataloader_specs(names))
            secrets = read_dataloader_secrets(self.__task_hash) or {}
            provisioned_here = True
        else:
            provisioned_here = False

        missing = [name for name in names if name not in secrets]
        if missing:
            raise ValueError(
                f"Task references dataloader(s) {missing} but no secrets were "
                "provisioned for them (see `qall dataloader add`)."
            )
        return path, provisioned_here

    def _create_proxy_function(
        self,
        child_name: str,
        child_hash: str,
        parent_task_id: str,
        is_async: bool = False,
        worker_addresses: Optional[list] = None,
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

        return textwrap.dedent(f"""
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
        """)


### Helpers ###


def _child_task_is_async(
    registry: BlockRegistry,
    child_hash: str,
    child_name: str,
) -> bool:
    """
    Determines whether a child task's entrypoint is an ``async def``.

    The runtime proxy replaces every child call in the parent's source. Whether
    that proxy must be generated as ``async def`` (the child is awaited or
    scheduled via ``asyncio.TaskGroup``/``gather``/...) or as plain ``def`` is a
    property of the child task itself, not of how the parent happens to call
    it. The child's own payload source is therefore the ground truth.

    Raises ``RuntimeError`` when the child's function kind cannot be determined
    (missing block, unparsable source, no matching definition, or ambiguous
    multiple definitions) instead of silently guessing a proxy shape that would
    diverge from the real task.
    """
    try:
        child_node = registry.get_node_from_local(hash=child_hash)
        child_payload = registry.get_payload_from_local(hash=child_node.payload_hash)
        tree = ast.parse(_get_source(child_payload))
    except Exception as exc:
        raise RuntimeError(
            f"Unable to determine whether child task {child_name!r} (hash "
            f"{child_hash}) is an async function: {exc}"
        ) from exc

    defs = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == child_name
    ]
    if not defs:
        defs = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == child_name
        ]
    if not defs:
        raise RuntimeError(
            f"Child task {child_name!r} (hash {child_hash}) does not define a "
            f"function named {child_name!r} in its payload source; cannot "
            "determine whether its runtime proxy should be async."
        )
    if len(defs) > 1:
        raise RuntimeError(
            f"Child task {child_name!r} (hash {child_hash}) has multiple "
            f"definitions of {child_name!r} in its payload source; cannot "
            "unambiguously determine whether its runtime proxy should be async."
        )

    return isinstance(defs[0], ast.AsyncFunctionDef)


def _get_source(payload: TaskPayload) -> str:
    if payload.code_format == "raw":
        return payload.code
    elif payload.code_format == "qio.program":
        program = Program.from_json_dict(payload.code)
        return program.to_python_source()
    else:
        raise NotImplementedError(f"Unknown code format '{payload.code_format}'")
