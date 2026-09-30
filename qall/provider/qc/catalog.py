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
import yaml

from importlib.resources import files

from qall.object import WorkerEntry


class WorkerCatalog:
    def __init__(self) -> None:
        self.__entries: dict[str, WorkerEntry] = self.__load()

    @property
    def entries(self) -> list[WorkerEntry]:
        return list(self.__entries.values())

    def get(self, worker: str) -> WorkerEntry:
        try:
            return self.__entries[worker]
        except KeyError:
            raise KeyError(f"Unknown worker: {worker}") from None

    def get_by_provider(self, provider: str) -> list[WorkerEntry]:
        return [
            entry for entry in self.__entries.values() if entry.provider == provider
        ]

    def find(
        self,
        provider: str,
        input_format: str,
    ) -> WorkerEntry | None:
        for entry in self.__entries.values():
            if entry.provider == provider and input_format in entry.input_formats:
                return entry
        return None

    def add_and_save(self, key: str, entry: WorkerEntry):
        new_entries = self.__entries.copy()
        new_entries[key] = entry
        self.__save(new_entries)
        self.__entries = self.__load()

    def batch_add_and_save(self, entries: dict[str, WorkerEntry]):
        new_entries = self.__entries.copy()
        new_entries.update(entries)
        self.__save(new_entries)
        self.__entries = self.__load()

    def __load(self) -> dict[str, WorkerEntry]:
        catalog_file = files("qall").joinpath("data", "worker_catalog.yml")

        try:
            with catalog_file.open("r", encoding="utf-8") as file:
                data = yaml.safe_load(file) or {}
            return {name: WorkerEntry.from_dict(entry) for name, entry in data.items()}
        except FileNotFoundError:
            return {}

    def __save(self, entries: dict[str, WorkerEntry]):
        catalog_file = files("qall").joinpath("data", "worker_catalog.yml")

        raw_data = {name: entry.to_dict() for name, entry in entries.items()}

        with catalog_file.open("w", encoding="utf-8") as file:
            yaml.safe_dump(raw_data, file, sort_keys=False)
