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
Git-like sharded sharding mechanism for underlying payload byte caching.
Optimizes performance via localized hash lookups.
"""

from __future__ import annotations

import shutil
import logging

from pathlib import Path
from typing import Optional

from .base import Blockstore

logger = logging.getLogger(__name__)


class LocalBlockstore(Blockstore):
    def __init__(
        self,
        root_dir: Path,
        max_block_size_mb: int = 1,
        read_only: bool = False,
    ):
        root_dir = root_dir if isinstance(root_dir, Path) else Path(root_dir)

        self.__blocks_dir = (root_dir or Path.cwd() / ".qall") / "blocks"
        self.__max_block_size = max_block_size_mb * 1024 * 1024
        self.__read_only = read_only

        self._ensure_structures()

    def _ensure_structures(self) -> None:
        if not self.__read_only:
            self.__blocks_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, file_hash: str) -> Path:
        return self.__blocks_dir / file_hash[:2] / file_hash[2:]

    def put(self, hash: str, data: bytes) -> bool:
        if self.__read_only:
            raise RuntimeError("put: local blockstore is in readonly")

        if len(data) > self.__max_block_size:
            raise ValueError("Payload size exceeds maximum allowed registry bounds.")

        path = self._get_path(hash)

        if path.exists():
            return False

        path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_bytes(data)
        tmp_path.rename(path)

        return True

    def has(self, hash: str) -> bool:
        return self._get_path(hash).exists()

    def get(self, hash: str) -> Optional[bytes]:
        path = self._get_path(hash)
        return path.read_bytes() if path.exists() else None

    def delete(self, hash: str) -> bool:
        if self.__read_only:
            raise RuntimeError("delete: local blockstore is in readonly")

        path = self._get_path(hash)

        if path.exists():
            path.unlink()
            return True

        return False

    def list(self) -> list[str]:
        hashes = []

        for dir in self.__blocks_dir.glob("**/*"):
            if dir.is_file():
                relative = dir.relative_to(self.__blocks_dir)
                if len(relative.parts) == 2:
                    hashes.append(relative.parts[0] + relative.parts[1])
        return hashes

    def clear(self) -> None:
        if self.__read_only:
            raise RuntimeError("clear: local blockstore is in readonly")

        if self.__blocks_dir.exists():
            deleted_hashes = self.list()
            for block_hash in deleted_hashes:
                logger.info(f"[LocalBlockstore] Deleted block: {block_hash}")

            shutil.rmtree(self.__blocks_dir)

        self._ensure_structures()
