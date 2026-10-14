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

import dataclasses
import re

from dataclasses import dataclass, field
from dataclasses_json import dataclass_json

# Credential keys considered sensitive: their plaintext value never lands in the
# user's qall-config.json, only in the host keyring (obfuscated placeholder).
SECRET_CREDENTIAL_KEYS = frozenset(
    {
        "api_key",
        "api-key",
        "apikey",
        "secret_key",
        "secret-key",
        "secret",
        "access_key",
        "access-key",
        "access_key_id",
        "access-key-id",
        "aws_secret_access_key",
        "aws-secret-access-key",
        "client_secret",
        "client-secret",
        "token",
        "password",
        "passwd",
        "private_key",
        "private-key",
        "key",
        "account_key",
        "account-key",
        "connection_string",
        "connection-string",
        "sas_token",
        "sas-token",
    }
)

_MASK = "****"

# Reasonable functional identifier (mirrors POSIX file-name constraints).
_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")


@dataclass_json
@dataclass(frozen=True)
class Dataloader:
    """
    Binds an arbitrary user-owned object storage as a virtual POSIX filesystem
    mount point inside tasks referencing it (see ``TaskSpec.dataloaders``).

    ``creds`` holds the storage-options required by the ``fsspec`` backend of
    ``src``. Sensitive values (see :data:`SECRET_CREDENTIAL_KEYS`) are stored
    obfuscated in ``qall-config.json`` and resolved from the host keyring at
    bind time.
    """

    name: str
    src: str
    dst: str
    creds: dict = field(default_factory=dict)

    @staticmethod
    def is_secret_key(key: str) -> bool:
        return key.lower().strip() in SECRET_CREDENTIAL_KEYS

    @staticmethod
    def validate_name(name: str) -> None:
        if not _NAME_RE.match(name):
            raise ValueError(
                f"Invalid dataloader name {name!r}: must match "
                f"{_NAME_RE.pattern!r}."
            )

    def redacted(self) -> "Dataloader":
        """Returns a copy whose sensitive credentials are masked for display."""
        return dataclasses.replace(
            self,
            creds={
                k: _MASK if self.is_secret_key(k) else v for k, v in self.creds.items()
            },
        )
