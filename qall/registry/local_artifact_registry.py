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

import sqlite3

from datetime import datetime
from pathlib import Path
from typing import Optional

from qall.object import LocalArtifact
from qall.config.paths import DEFAULT_ARTIFACT_REGISTRY_PATH

from .blockstore import LocalBlockstore

_METADATA_DB = "daemon_state.db"


def _parse_sqlite_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load_metadata(root_dir: Path) -> dict[str, LocalArtifact]:
    """
    Best-effort load of artifact metadata persisted by the daemon in its
    sqlite metadata store. The store is recreated on every daemon start, so
    missing or unreadable databases simply yield no metadata.
    """
    db_path = root_dir / _METADATA_DB

    if not db_path.exists():
        return {}

    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row

        try:
            rows = con.execute(
                "SELECT hash, task_run_id, created_at FROM artifacts_meta"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}

    metadata: dict[str, LocalArtifact] = {}

    for row in rows:
        hash = row["hash"]
        if hash in metadata:
            continue

        metadata[hash] = LocalArtifact(
            hash=hash,
            size=0,
            task_run_id=row["task_run_id"],
            created_at=_parse_sqlite_datetime(row["created_at"]),
        )

    return metadata


class LocalArtifactRegistry:
    """
    Read-only access to artifacts stored on the host at the default artifact
    registry location, i.e. the content-addressed block store the daemon writes
    into when running tasks locally.
    """

    def __init__(
        self,
        root_dir: Path | str = DEFAULT_ARTIFACT_REGISTRY_PATH,
        read_only: bool = True,
    ):
        self.__root_dir = root_dir if isinstance(root_dir, Path) else Path(root_dir)
        self.__blockstore = LocalBlockstore(
            root_dir=self.__root_dir, read_only=read_only
        )
        self.__metadata = _load_metadata(self.__root_dir)

    @property
    def root_dir(self) -> Path:
        return self.__root_dir

    def list(self) -> list[LocalArtifact]:
        artifacts = []

        for hash in self.__blockstore.list():
            data = self.__blockstore.get(hash)
            meta = self.__metadata.get(hash, None)

            artifacts.append(
                LocalArtifact(
                    hash=hash,
                    size=len(data) if data is not None else 0,
                    task_run_id=meta.task_run_id if meta else None,
                    created_at=meta.created_at if meta else None,
                )
            )

        return sorted(artifacts, key=lambda a: (a.created_at or datetime.min, a.hash))

    def get(self, hash: str) -> LocalArtifact:
        data = self.__blockstore.get(hash)

        if data is None:
            raise FileNotFoundError(
                f"Artifact {hash} not found in local registry {self.__root_dir}"
            )

        meta = self.__metadata.get(hash, None)

        return LocalArtifact(
            hash=hash,
            size=len(data),
            task_run_id=meta.task_run_id if meta else None,
            created_at=meta.created_at if meta else None,
        )

    def read_bytes(self, hash: str) -> bytes:
        data = self.__blockstore.get(hash)

        if data is None:
            raise FileNotFoundError(
                f"Artifact {hash} not found in local registry {self.__root_dir}"
            )

        return data
