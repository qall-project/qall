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
import rustworkx as rx

from urllib.parse import urlparse
from pathlib import Path

from qall.object import (
    Tag,
    TaskDag,
    TaskResource,
    TaskMetadata,
    TaskEnvironment,
    TaskPayload,
    TaskNode,
    Block,
    ClassicalResourceConstraints,
    QuantumResourceConstraints,
    WorkerDag,
    WorkerNode,
    WorkerPayload,
)
from qall.specification import WorkflowSpec, TaskSpec, WorkerSpec
from qall.codec import DEFAULT_CODEC
from qall_registry_client.v1 import (
    GrpcRegistryClient,
    pull,
    push,
)

from qio.core.program import Program

from .login import RegistryCredentials
from .local_block_registry import LocalBlockRegistryClient


def _get_task_spec_metadata(spec: TaskSpec) -> TaskMetadata:
    return TaskMetadata(
        name=spec.name,
        entrypoint=spec.entrypoint,
        pure=spec.pure,
        retry=spec.retry,
    )


def _get_task_spec_resource(spec: TaskSpec) -> TaskResource:
    classical = ClassicalResourceConstraints(**spec.classical_resources)
    quantum = QuantumResourceConstraints(**spec.quantum_resources)

    return TaskResource(classical=classical, quantum=quantum)


def _get_task_spec_payload(spec: TaskSpec) -> TaskPayload:
    full_code_blocks = []

    if spec.imports and "external_imports" in spec.imports:
        for ext_import in spec.imports["external_imports"]:
            full_code_blocks.append(ext_import)

    if spec.local_dependencies:
        for dep_source in spec.local_dependencies.values():
            full_code_blocks.append(dep_source)
    full_code_blocks.append(spec.source)

    # Build a single unified source layout
    compiled_source = "\n\n".join(full_code_blocks)

    # Leverage qio to pack, compress and normalize the source representation
    qio_program = Program.from_python_source(compiled_source)

    return TaskPayload(
        code=qio_program.to_json_dict(),
        code_format="qio.program",
        environment=TaskEnvironment(
            image=spec.image, requirements=spec.requirements
        ).to_dict(),
        metadata={"quantum_runs": spec.quantum_runs},
    )


class BlockRegistry:
    def __init__(
        self,
        local_root_dir: Path | str = Path().home() / ".cache/qall/block-registry",
        read_only: bool = False,
    ):
        self.__remote_client: GrpcRegistryClient = None

        if isinstance(local_root_dir, str):
            local_root_dir = Path(local_root_dir)
        self.__local_client = LocalBlockRegistryClient(
            root_dir=local_root_dir, read_only=read_only
        )
        self.__codec = DEFAULT_CODEC

    @property
    def remote_domain(self) -> str:
        if not self.__remote_client:
            raise RuntimeError("You must login first to access remote task registry.")
        domain = urlparse(self.__remote_client.url).netloc

        return domain

    @property
    def local_root_dir(self) -> str:
        return self.__local_client.root_dir

    def clear(self):
        self.__local_client.clear()

    def login(self, credentials: RegistryCredentials) -> bool:
        if not credentials or not credentials.domain:
            return False

        namespace = credentials.credentials.get("namespace")
        token = credentials.credentials.get("token")

        self.__remote_client = GrpcRegistryClient(
            url=credentials.domain, namespace=namespace, token=token
        )

        return True

    def create_workflow_dag(self, spec: WorkflowSpec) -> TaskDag:
        """
        Compiles the call graph into decoupled registry-compliant blocks.
        Resolves individual signatures and walks the graph bottom-up (reversed topological sort)
        to link parent nodes with their immutable sub-dependencies.
        """
        if spec.graph is None or not spec.entrypoint_task:
            raise RuntimeError(
                "Cannot extract manifest: Graph or entrypoint task is missing."
            )

        registry_payloads = []
        task_to_p_hash = {}

        # 1. Compile immutable building blocks for all tasks
        for name, task in spec.tasks.items():
            p_reg = _get_task_spec_payload(task)
            registry_payloads.append(p_reg)
            task_to_p_hash[name] = p_reg.to_block(self.__codec).hash

        # 2. Trace execution edges from leaves up to the root element
        registry_nodes = []
        node_name_to_node_hash = {}

        # Reversed topological sort guarantees children hashes are computed before their callers
        topological_order = rx.topological_sort(spec.graph)

        for node_idx in reversed(topological_order):
            task_name = spec.graph.get_node_data(node_idx)
            task = spec.tasks.get(task_name)

            # Find downstream successors to link as children hashes
            children_mapping = {}

            # spec.graph.successors yields task name strings directly
            for child_task_name in spec.graph.successors(node_idx):
                if child_task_name in node_name_to_node_hash:
                    children_mapping[child_task_name] = node_name_to_node_hash[
                        child_task_name
                    ]

            # Reconstruct the decoupled registry architecture mapping layout
            reg_node = TaskNode(
                payload_hash=task_to_p_hash[task_name],
                children=children_mapping,
                resources=_get_task_spec_resource(spec=task).to_dict(),
                metadata=_get_task_spec_metadata(spec=task).to_dict(),
            )

            node_block = reg_node.to_block(self.__codec)
            registry_nodes.append(reg_node)
            node_name_to_node_hash[task_name] = node_block.hash

        # The global workflow tracker root hash maps onto the entrypoint element
        root_hash = node_name_to_node_hash[spec.entrypoint_task.name]

        return TaskDag(registry_payloads, registry_nodes, root_hash)

    def create_worker_dag(self, spec: WorkerSpec) -> WorkerDag:
        """
        Converts a WorkerSpec into the immutable blocks stored in the registry.

        A Worker is intentionally represented by a single WorkerNode referencing
        a single WorkerPayload. Contrary to a workflow, there is no execution
        graph to traverse: a Worker is a single long-lived executable component.
        """

        if not spec.source:
            raise RuntimeError(
                f"Cannot create worker DAG for '{spec.name}': source is missing."
            )

        full_code_blocks = []

        if spec.imports and "external_imports" in spec.imports:
            full_code_blocks.extend(spec.imports["external_imports"])

        if spec.local_dependencies:
            full_code_blocks.extend(spec.local_dependencies.values())

        full_code_blocks.append(spec.source)

        compiled_source = "\n\n".join(full_code_blocks)

        qio_program = Program.from_python_source(compiled_source)

        payload = WorkerPayload(
            code=qio_program.to_json_dict(),
            code_format="qio.program",
            environment={
                "image": spec.image,
                "requirements": sorted(spec.requirements),
            },
        )

        metadata = {
            "name": spec.name,
            "provider": spec.provider,
            "input_format": spec.input_format,
            "output_format": spec.output_format,
            # "resources": sorted(spec.resources),
        }

        node = WorkerNode(
            payload_hash=payload.to_block(self.__codec).hash,
            metadata=metadata,
        )

        root_hash = node.to_block(self.__codec).hash

        return WorkerDag(
            nodes=[node],
            payloads=[payload],
            root_hash=root_hash,
        )

    def push(self, tag: Tag, dag: TaskDag | WorkerDag) -> str:
        if not self.__remote_client and not self.__local_client:
            raise RuntimeError("No registry client is available for pushing.")

        hash = dag.root_hash
        elements = dag.items  # nodes, payloads...

        blocks: list[Block] = []
        block_hashes: list[str] = []

        for component in elements:
            block = component.to_block(self.__codec)
            blocks.append(block)
            block_hashes.append(block.hash)

        push_result = None

        if self.__local_client:
            push_result = push(
                client=self.__local_client,
                name=tag.name,
                blocks=blocks,
                version=tag.version,
                root_hash=hash,
            )

        if self.__remote_client:
            push_result = push(
                client=self.__remote_client,
                name=tag.name,
                blocks=blocks,
                version=tag.version,
                root_hash=hash,
            )

        if push_result:
            return push_result.tag_uri

        return None

    def get_node_from_local(self, hash: str) -> TaskNode:
        block = self._get_local_block(hash)

        return TaskNode.from_block(block, self.__codec)

    def get_payload_from_local(self, hash: str) -> TaskPayload:
        block = self._get_local_block(hash)

        return TaskPayload.from_block(block, self.__codec)

    def get_worker_node_from_local(self, hash: str) -> WorkerNode:
        block = self._get_local_block(hash)

        return WorkerNode.from_block(block, self.__codec)

    def get_worker_payload_from_local(self, hash: str) -> WorkerPayload:
        block = self._get_local_block(hash)

        return WorkerPayload.from_block(block, self.__codec)

    def pull(self, tag: Tag) -> str:
        if not self.__remote_client and not self.__local_client:
            raise RuntimeError("No registry client is available for pulling.")

        pull_result = None

        def _next_get(node) -> list[str]:
            if isinstance(node, dict):
                next_hashes = []

                children = node.get("children", None)
                if children:
                    next_hashes.extend(node["children"].values())

                payload_hash = node.get("payload_hash", None)
                if payload_hash:
                    next_hashes.append(payload_hash)

                return next_hashes

        if self.__local_client:

            def _fallback_get(hashes: list[str]) -> list[Block]:
                if not self.__remote_client:
                    raise RuntimeError(
                        "Remote client is not available for fallback get."
                    )

                return self.__remote_client.get(hashes)

            pull_result = pull(
                client=self.__local_client,
                name=tag.name,
                version=tag.version,
                codec_check=self.__codec.check,
                codec_decode=self.__codec.decode,
                next_get=_next_get,
                fallback_get=_fallback_get,
            )
        elif self.__remote_client:
            pull_result = pull(
                client=self.__remote_client,
                name=tag.name,
                version=tag.version,
                codec_check=self.__codec.check,
                codec_decode=self.__codec.decode,
                next_get=_next_get,
            )

        if pull_result:
            return pull_result.root_hash

        return None

    def _get_local_block(self, hash: str) -> Block:
        if not self.__local_client:
            raise RuntimeError("Local client is not available for get_node_from_local.")

        blocks = self.__local_client.get([hash])

        if not blocks or len(blocks) == 0:
            raise RuntimeError(f"Block with hash '{hash}' not found in local registry.")

        block = blocks[0]
        if not self.__codec.check(block.data, block.hash):
            raise ValueError(
                f"Cryptographic integrity violation: block data verification "
                f"failed for expected hash '{block.hash}'."
            )

        return block
