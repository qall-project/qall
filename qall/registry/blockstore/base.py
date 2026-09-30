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
Abstract block store interface.

The block store is the lowest-level persistence primitive in Qall.
It stores raw bytes indexed by their hash. All higher-level objects
(Payload, ResourceConstraints, GraphNode) are serialized to bytes
and stored here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class Blockstore(ABC):
    """
    Content-addressed key-value store: hash → bytes.
    All operations are idempotent.
    """

    @abstractmethod
    def put(self, hash: str, data: bytes) -> bool:
        """
        Store a block.
        Returns True if newly created, False if already existed.
        Raises ValueError if data exceeds the size limit.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, hash: str) -> Optional[bytes]:
        """Retrieve a block. Returns None if not found."""
        raise NotImplementedError

    @abstractmethod
    def has(self, hash: str) -> bool:
        """Return True if the block exists in the store."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, hash: str) -> bool:
        """Delete a block. Returns True if deleted, False if not found."""
        raise NotImplementedError

    @abstractmethod
    def list(self) -> list[str]:
        """List all block hashes in the store."""
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        """
        Completely erases the database, unlinking all
        sharded binary files, deleting the remote origin tracking log, and
        wiping the active in-memory lookups. Restores an empty operational workspace.
        """
        raise NotImplementedError
