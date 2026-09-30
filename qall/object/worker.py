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
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qall.codec import Codec, DEFAULT_CODEC

from .block import Block


@dataclass(frozen=True)
class WorkerEnvironment:
    """Execution environment shared by a long-lived worker."""

    __TYPE = "worker_environment"

    image: str = "python:3.12"
    requirements: list[str] = field(default_factory=list)
    type: str = field(default=__TYPE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image": self.image,
            "requirements": sorted(self.requirements),
            "type": self.__TYPE,
        }

    def to_block(self, codec: Codec = DEFAULT_CODEC) -> Block:
        h, d = codec.encode(self.to_dict())
        return Block(hash=h, data=d)

    @staticmethod
    def from_block(
        block: Block,
        codec: Codec = DEFAULT_CODEC,
    ) -> "WorkerEnvironment":
        data = codec.decode(block.data)

        if data.get("type") != WorkerEnvironment.__TYPE:
            raise RuntimeError(
                "worker_environment.from_block failed due to different "
                f"type of raw block data {data.get('type', '')}"
            )

        return WorkerEnvironment(
            image=data.get("image", "python:3.12"),
            requirements=list(data.get("requirements", [])),
        )


@dataclass(frozen=True)
class WorkerPayload:
    __TYPE = "worker_payload"

    code: str = field(default="")
    code_format: str = field(default="")
    environment: dict = field(default_factory=dict)
    type: str = field(default=__TYPE)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "code_format": self.code_format,
            "environment": self.environment,
            "type": self.__TYPE,
        }

    def to_block(self, codec: Codec = DEFAULT_CODEC) -> Block:
        h, d = self._encode(codec)
        return Block(hash=h, data=d)

    @staticmethod
    def from_block(
        block: Block,
        codec: Codec = DEFAULT_CODEC,
    ) -> "WorkerPayload":
        data = codec.decode(block.data)

        if WorkerPayload.__TYPE != data.get("type", ""):
            raise RuntimeError(
                "WorkerPayload.from_block failed due to different "
                f"type of raw block data {data.get('type', '')}"
            )

        return WorkerPayload(
            code=data.get("code", ""),
            code_format=data.get("code_format", ""),
            environment=data.get("environment", {}),
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
class WorkerMetadata:
    """Declarative metadata used to resolve and expose a worker."""

    __TYPE = "worker_metadata"

    name: str = ""
    provider: str = ""
    input_format: str = ""
    output_format: str = ""
    type: str = field(default=__TYPE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "input_format": self.input_format,
            "output_format": self.output_format,
            "type": self.__TYPE,
        }

    def to_block(self, codec: Codec = DEFAULT_CODEC) -> Block:
        h, d = codec.encode(self.to_dict())
        return Block(hash=h, data=d)

    @staticmethod
    def from_block(
        block: Block,
        codec: Codec = DEFAULT_CODEC,
    ) -> "WorkerMetadata":
        data = codec.decode(block.data)
        if data.get("type") != WorkerMetadata.__TYPE:
            raise RuntimeError(
                "worker_metadata.from_block failed due to different "
                f"type of raw block data {data.get('type', '')}"
            )

        return WorkerMetadata(
            name=data.get("name", ""),
            provider=data.get("provider", ""),
            input_format=data.get("input_format", ""),
            output_format=data.get("output_format", ""),
        )


@dataclass(frozen=True)
class WorkerNode:
    __TYPE = "worker_node"

    payload_hash: str = field(default="")
    metadata: dict = field(default_factory=dict)
    type: str = field(default=__TYPE)

    def to_dict(self) -> dict:
        return {
            "payload_hash": self.payload_hash,
            "metadata": self.metadata,
            "type": self.__TYPE,
        }

    def to_block(self, codec: Codec = DEFAULT_CODEC) -> Block:
        h, d = self._encode(codec)
        return Block(hash=h, data=d)

    @staticmethod
    def from_block(
        block: Block,
        codec: Codec = DEFAULT_CODEC,
    ) -> "WorkerNode":
        data = codec.decode(block.data)

        if WorkerNode.__TYPE != data.get("type", ""):
            raise RuntimeError(
                "WorkerNode.from_block failed due to different "
                f"type of raw block data {data.get('type', '')}"
            )

        return WorkerNode(
            payload_hash=data.get("payload_hash", ""),
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
class WorkerDag:
    nodes: list[WorkerNode]
    payloads: list[WorkerPayload]
    root_hash: str

    def __repr__(self):
        return self.root_hash

    @property
    def items(self):
        return self.nodes + self.payloads
