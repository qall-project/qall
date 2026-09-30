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

from dag import Block
from dag.codecs import dag_cbor

from abc import ABC, abstractmethod
from typing import Any, Tuple


class Codec(ABC):
    """
    Deterministic codec: encodes a dict to bytes and computes its hash.
    Implementations must guarantee that the same input always produces
    the same bytes — i.e. map keys must be sorted.
    """

    @abstractmethod
    def encode(self, value: dict[str, Any]) -> Tuple[str, bytes]:
        """Encode a dict to bytes deterministically."""
        raise NotImplementedError

    @abstractmethod
    def decode(self, data: bytes) -> dict[str, Any]:
        """Decode bytes back to a dict."""
        raise NotImplementedError

    @abstractmethod
    def check(self, data: bytes, expected_hash: str) -> bool:
        """Check that the hash of the decoded data matches the expected hash."""
        raise NotImplementedError


class DagCborCodec(Codec):
    """
    IPLD DAG-CBOR codec via py-ipld-dag.
    Provides deterministic CBOR encoding with CID link support.
    """

    def encode(self, value: dict[str, Any]) -> Tuple[str, bytes]:
        block = Block.encode(value=value, codec=dag_cbor.codec, version=1)
        return str(block.cid), block.bytes

    def decode(self, data: bytes) -> dict[str, Any]:
        block = Block.decode(data=data, codec=dag_cbor.codec, version=1)
        return block.value

    def check(self, data: bytes, expected_hash: str) -> bool:
        block = Block.decode(data=data, codec=dag_cbor.codec, version=1)
        return str(block.cid) == expected_hash


def get_default_codec() -> Codec:
    return DagCborCodec()


DEFAULT_CODEC: Codec = get_default_codec()
