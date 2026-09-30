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
from pathlib import Path

from qio.core.program import Program

from qall.object import (
    WorkerNode,
    WorkerPayload,
    WorkerMetadata,
)
from qall.registry import BlockRegistry
from qall.provider.worker import QuantumWorker, QuantumWorkerApi


class WorkerRuntimeExecutor:
    def __init__(
        self,
        worker_hash: str,
        registry: Path | str | BlockRegistry,
        port: str | int,
    ):
        self.__block_registry = (
            BlockRegistry(registry, read_only=True)
            if isinstance(registry, (Path, str))
            else registry
        )
        self.__worker_hash = worker_hash
        self.__port = str(port)

    def execute(self) -> None:
        node: WorkerNode = self.__block_registry.get_worker_node_from_local(
            hash=self.__worker_hash
        )
        if not node:
            raise ValueError(
                f"No WorkerNode found in local store for hash: {self.__worker_hash}"
            )
        print(f"[WorkerExecutor] WorkerNode loaded: {node.hash}")

        payload: WorkerPayload = self.__block_registry.get_worker_payload_from_local(
            hash=node.payload_hash
        )

        if not payload:
            raise ValueError(
                f"No WorkerPayload associated with hash {self.__worker_hash} in local store."
            )

        metadata = WorkerMetadata(**node.metadata)

        print(f"[WorkerExecutor] Payload and metadata loaded: {metadata}")

        worker = self._load_worker(
            payload=payload,
            metadata=metadata,
        )

        server = QuantumWorkerApi(worker)
        server.serve(port=self.__port)

    def _load_worker(
        self,
        payload: WorkerPayload,
        metadata: WorkerMetadata,
    ) -> QuantumWorker:
        """
        Reconstruct the QuantumWorker contained in the WorkerPayload.
        """
        namespace = {}

        try:
            source_code = _get_source(payload)
            exec(
                source_code,
                namespace,
                namespace,
            )
        except Exception as exc:
            raise RuntimeError("Failed to load QuantumWorker code") from exc

        worker_class = self._find_worker_class(
            namespace,
            metadata,
        )

        if worker_class is None:
            raise RuntimeError("No QuantumWorker class found in worker payload")

        try:
            worker = worker_class()
            worker.set_capabilities(metadata.input_format, metadata.output_format)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to instantiate QuantumWorker {worker_class.__name__}"
            ) from exc

        if not isinstance(worker, QuantumWorker):
            raise TypeError(
                f"Worker class {worker_class.__name__} does not inherit from QuantumWorker"
            )

        return worker

    def _find_worker_class(
        self,
        namespace: dict,
        metadata: WorkerMetadata,
    ):
        worker_class_name = getattr(metadata, "name", None) or getattr(
            metadata, "class_name", None
        )

        if worker_class_name:
            worker_class = namespace.get(worker_class_name)
            if worker_class is not None and isinstance(worker_class, type):
                return worker_class

        candidates = []

        for obj in namespace.values():
            if not isinstance(obj, type):
                continue
            if obj is QuantumWorker:
                continue
            try:
                if issubclass(obj, QuantumWorker):
                    candidates.append(obj)
            except TypeError:
                continue

        if len(candidates) == 0:
            return None
        if len(candidates) > 1:
            raise RuntimeError(
                "Multiple QuantumWorker implementations found in worker payload"
            )

        return candidates[0]


def _get_source(payload: WorkerPayload) -> str:
    if payload.code_format == "raw":
        return payload.code
    elif payload.code_format == "qio.program":
        program = Program.from_json_dict(payload.code)
        return program.to_python_source()
    else:
        raise NotImplementedError(f"Unknown code format '{payload.code_format}'")
