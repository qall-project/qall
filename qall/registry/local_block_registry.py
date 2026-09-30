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
from typing import List
from pathlib import Path

from qall_registry_client.v1.client.base import RegistryClient
from qall_registry_client.v1.objects import Block, Tag

from .blockstore import LocalBlockstore
from .datastore import LocalDatastore


class LocalBlockRegistryClient(RegistryClient):
    def __init__(
        self, root_dir: Path, max_block_size_mb: int = 1, read_only: bool = False
    ):
        self.__root_dir = root_dir
        self.__blockstore = LocalBlockstore(
            root_dir=root_dir, max_block_size_mb=max_block_size_mb, read_only=read_only
        )
        self.__datastore = LocalDatastore(root_dir=root_dir, read_only=read_only)

    @property
    def root_dir(self) -> str:
        return str(self.__root_dir.resolve())

    def check(self, hashes: List[str]) -> List[str]:
        return [h for h in hashes if not self.__blockstore.has(h)]

    def get(self, hashes: List[str]) -> List[Block]:
        blocks = []

        for h in hashes:
            data = self.__blockstore.get(h)
            if data is not None:
                blocks.append(Block(hash=h, data=data))

        return blocks

    def push(self, blocks: List[Block]) -> int:
        count = 0

        for block in blocks:
            if not self.__blockstore.has(block.hash):
                self.__blockstore.put(block.hash, block.data)
                count += 1

        return count

    def tag(self, tag: Tag) -> str:
        self.__datastore.put_tag(tag)
        return f"{tag.name}:{tag.version}"

    def resolve(self, name: str, version: str) -> str:
        root_hash, _ = self.__datastore.resolve_tag(name, version)
        return root_hash

    def list_tags(self, name: str) -> List[Tag]:
        return self.__datastore.list_tags(name)

    def untag(self, name: str, version: str) -> bool:
        return self.__datastore.delete_tag(name, version)

    def clear(self):
        self.__blockstore.clear()
        self.__datastore.clear()
