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
from dataclasses import dataclass, field
from typing import Optional

from qall.codec import Codec, DEFAULT_CODEC

from .block import Block
from .resource_contraint import ClassicalResourceConstraints, QuantumResourceConstraints


@dataclass(frozen=True)
class TaskPayload:
    """
    The smallest executable unit of computation.
    Stores normalized source code and its execution environment.
    Immutable once created — any change produces a new hash.
    """

    __TYPE = "task_payload"

    code: str = field(default="")
    code_format: str = field(default="")
    environment: dict = field(default_factory=dict)
    runtime: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    type: str = field(default=__TYPE)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "code_format": self.code_format,
            "environment": self.environment,
            "runtime": self.runtime,
            "metadata": self.metadata,
            "type": self.__TYPE,
        }

    def to_block(self, codec: Codec = DEFAULT_CODEC) -> Block:
        h, d = self._encode(codec)
        return Block(hash=h, data=d)

    @staticmethod
    def from_block(block: Block, codec: Codec = DEFAULT_CODEC) -> "TaskPayload":
        data = codec.decode(block.data)

        block_type = data.get("type", "")
        if TaskPayload.__TYPE != block_type:
            raise RuntimeError(
                f"payload.from_block failed due to different type of raw block data {block_type}"
            )

        return TaskPayload(
            code=data.get("code", ""),
            code_format=data.get("code_format", ""),
            environment=data.get("environment", {}),
            runtime=data.get("runtime", {}),
            metadata=data.get("metadata", {}),
        )

    @property
    def hash(self) -> str:
        h, _ = self._encode()
        return h

    @property
    def data(self) -> bytes:
        _, d = self._encode()
        return d

    def _encode(self, codec: Codec = DEFAULT_CODEC):
        return codec.encode(self.to_dict())


@dataclass(frozen=True)
class TaskNode:
    """
    Placement of a TaskPayload within a computation graph.

    node_hash = Hash(task_payload_hash, children, metadata, resources)

    Merkle property: any change in a child node propagates upward
    through the graph via hash changes. Two nodes are identical if and
    only if their payload, constraints, and full dependency subgraph are identical.
    """

    __TYPE = "task_node"

    payload_hash: str = field(default="")
    resources: dict = field(default_factory=dict)
    children: dict[str, str] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    type: str = field(default=__TYPE)

    def to_dict(self) -> dict:
        return {
            "payload_hash": self.payload_hash,
            "resources": self.resources,
            "children": self.children,
            "metadata": self.metadata,
            "type": self.__TYPE,
        }

    def to_block(self, codec: Codec = DEFAULT_CODEC) -> Block:
        h, d = self._encode(codec)
        return Block(hash=h, data=d)

    @staticmethod
    def from_block(block: Block, codec: Codec = DEFAULT_CODEC) -> "TaskNode":
        data = codec.decode(block.data)

        block_type = data.get("type", "")
        if TaskNode.__TYPE != block_type:
            raise RuntimeError(
                f"node.from_block failed due to different type of raw block data {block_type}"
            )

        return TaskNode(
            payload_hash=data.get("payload_hash", ""),
            resources=data.get("resources", {}),
            children=data.get("children", {}),
            metadata=data.get("metadata", {}),
        )

    @property
    def hash(self) -> str:
        h, _ = self._encode()
        return h

    @property
    def data(self) -> bytes:
        _, d = self._encode()
        return d

    def _encode(self, codec: Codec = DEFAULT_CODEC):
        return codec.encode(self.to_dict())


@dataclass(frozen=True)
class TaskEnvironment:
    """OCI execution environment for a task."""

    __TYPE = "task_environment"

    image: str
    requirements: list[str, ...] = field(default_factory=list)
    type: str = field(default=__TYPE)

    def to_dict(self) -> dict:
        return {
            "image": self.image,
            "requirements": sorted(self.requirements),
            "type": self.__TYPE,
        }


@dataclass(frozen=True)
class TaskMetadata:
    __TYPE = "task_metadata"

    name: str = field(default="")
    entrypoint: bool = field(default=False)
    pure: bool = field(default=True)
    retry: Optional[int] = field(default=0)
    max_duration: Optional[str] = field(default=None)
    type: str = field(default=__TYPE)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "entrypoint": self.entrypoint,
            "pure": self.pure,
            "retry": self.retry,
            "max_duration": self.max_duration,
            "type": self.__TYPE,
        }


@dataclass(frozen=True)
class TaskResource:
    __TYPE = "task_resource"

    classical: Optional[ClassicalResourceConstraints] = field(default=None)
    quantum: Optional[QuantumResourceConstraints] = field(default=None)
    type: str = field(default=__TYPE)

    def to_dict(self) -> dict:
        return {
            "classical": self.classical.to_dict() if self.classical else None,
            "quantum": self.quantum.to_dict() if self.quantum else None,
            "type": self.__TYPE,
        }


@dataclass(frozen=True)
class TaskDag:
    nodes: list[TaskNode]
    payloads: list[TaskPayload]
    root_hash: str

    def __repr__(self):
        return self.root_hash

    @property
    def items(self):
        return self.nodes + self.payloads
