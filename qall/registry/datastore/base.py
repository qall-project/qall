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

from abc import ABC, abstractmethod


class Datastore(ABC):

    @abstractmethod
    def put_tag(self, tag: dict) -> None:
        raise NotImplementedError

    @abstractmethod
    def put_tags(self, tags: list[dict]) -> None:
        raise NotImplementedError

    @abstractmethod
    def resolve_tag(self, name: str, version: str) -> tuple[str | None, bool]:
        raise NotImplementedError

    @abstractmethod
    def list_tags(self, name: str) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def delete_tag(self, name: str, version: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def clear(self):
        raise NotImplementedError
