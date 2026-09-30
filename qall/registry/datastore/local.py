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

import json
import os

import lmdb

from pathlib import Path

from qall_registry_client.v1.objects import Tag


class LocalDatastore:

    def __init__(
        self,
        root_dir: Path,
        size_mb: int = 100,
        read_only: bool = False,
    ):
        root_dir = root_dir if isinstance(root_dir, Path) else Path(root_dir)

        self.__data_dir = (root_dir or Path.cwd() / ".qall") / "data"

        if not read_only:
            os.makedirs(self.__data_dir, exist_ok=True)

        self.__env = lmdb.open(
            f"{self.__data_dir}/datastore.db",
            map_size=size_mb * 1024 * 1024,
            subdir=False,
            readonly=read_only,
        )

    def close(self) -> None:
        self.__env.close()

    def put_tag(self, tag: Tag) -> None:
        key = tag.uri.encode("utf-8")
        data = json.dumps(tag.to_dict()).encode("utf-8")

        with self.__env.begin(write=True) as txn:
            txn.put(key, data)

    def put_tags(self, tags: list[Tag]) -> None:
        with self.__env.begin(write=True) as txn:
            for tag in tags:
                key = tag.uri.encode("utf-8")
                data = json.dumps(tag.to_dict()).encode("utf-8")
                txn.put(key, data)

    def resolve_tag(self, name: str, version: str) -> tuple[str | None, bool]:
        key = f"{name}:{version}".encode("utf-8")

        with self.__env.begin(write=False) as txn:
            val = txn.get(key)
            if val is None:
                return None, False

            tag_data = json.loads(val.decode("utf-8"))
            return tag_data.get("root_hash"), True

    def list_tags(self, name: str) -> list[Tag]:
        prefix = f"{name}:".encode("utf-8")
        tags = []

        with self.__env.begin(write=False) as txn:
            cursor = txn.cursor()
            if cursor.set_range(prefix):
                for k, v in cursor:
                    if not k.startswith(prefix):
                        break

                    tag_data = json.loads(v.decode("utf-8"))
                    tags.append(Tag(**tag_data))

        return tags

    def delete_tag(self, name: str, version: str) -> bool:
        key = f"{name}:{version}".encode("utf-8")

        with self.__env.begin(write=True) as txn:
            return txn.delete(key)

    def clear(self) -> None:
        pass
