# Copyright 2026 Scaleway
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from qall_daemon_client import GrpcDaemonClient


# ArtifactBackend was made for development purposes before the daemon was available, see if still relevant to keep the daemonless artifact backend (LocalArtifactBackend).
class ArtifactBackend(ABC):
    @abstractmethod
    def download_artifact(self, artifact_hash: str) -> bytes:
        pass

    @abstractmethod
    def upload_artifact(self, task_run_id: str, artifact_bytes: bytes) -> str:
        pass


class DaemonArtifactBackend(ArtifactBackend):
    def __init__(self, daemon_address: str, token: Optional[str] = None):
        self.__daemon_address = daemon_address

        if not token:
            token_path = os.environ.get("QALL_TOKEN_PATH", "/run/secrets/qall_token")

            with open(token_path, "r") as f:
                token = f.read().strip()

        self.__token = token

    def download_artifact(self, artifact_hash: str) -> bytes:
        with GrpcDaemonClient(url=self.__daemon_address, token=self.__token) as client:
            response = client.download_artifact(artifact_hash)
            return response

    def upload_artifact(self, task_run_id: str, artifact_bytes: bytes) -> str:
        with GrpcDaemonClient(url=self.__daemon_address, token=self.__token) as client:
            artifact = client.create_artifact(task_run_id, artifact_bytes)
            return artifact.hash


class LocalArtifactBackend(ArtifactBackend):
    def __init__(self, artifact_dir: Optional[Path] = None):
        self.__artifact_dir = (
            Path(artifact_dir) if artifact_dir else Path.cwd() / ".qall" / "artifacts"
        )
        self.__artifact_dir.mkdir(parents=True, exist_ok=True)
        self.__counter = 0

    def _extract_hash(self, artifact_hash: str) -> str:
        if artifact_hash.startswith("local:"):
            return artifact_hash[6:]
        return artifact_hash

    def download_artifact(self, artifact_hash: str) -> bytes:
        hash = self._extract_hash(artifact_hash)
        artifact_path = self.__artifact_dir / f"{hash}.bin"

        if not artifact_path.exists():
            raise FileNotFoundError(
                f"Artifact {artifact_hash} not found in {self.__artifact_dir}"
            )

        return artifact_path.read_bytes()

    def upload_artifact(self, task_run_id: str, artifact_bytes: bytes) -> str:
        import hashlib

        self.__counter += 1
        artifact_hash = hashlib.sha256(
            artifact_bytes + str(self.__counter).encode()
        ).hexdigest()[:16]
        artifact_path = self.__artifact_dir / f"{artifact_hash}.bin"
        artifact_path.write_bytes(artifact_bytes)

        return f"local:{artifact_hash}"
