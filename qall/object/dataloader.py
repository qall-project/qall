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
from urllib.parse import urlparse

from dataclasses_json import dataclass_json

# Credential keys considered sensitive: their plaintext value never lands in the
# user's config file (.qall.yml / qall-config.yml), only in the host keyring
# (obfuscated placeholder).
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

# Config scopes a dataloader may live in. ``local`` (the current project's
# ``.qall.yml``) takes precedence over ``global`` (the machine-wide
# ``qall-config.yml``) when both define the same name.
DATALOADER_SCOPES = ("local", "global")


@dataclass_json
@dataclass(frozen=True)
class DataloaderEntry:
    """
    Value-only persisted representation of a dataloader inside a
    ``LocalConfiguration`` (``profiles`` + ``dataloaders`` + ``version``).

    Keeps the YAML clean: the entry lives under the ``dataloaders:`` map keyed
    by dataloader name, so the name itself is not duplicated inside the entry.
    """

    src: str
    dst: str
    creds: dict = field(default_factory=dict)


@dataclass_json
@dataclass(frozen=True)
class Dataloader:
    """
    Binds an arbitrary user-owned object storage as a virtual POSIX filesystem
    mount point inside tasks referencing it (see ``TaskSpec.dataloaders``).

    ``creds`` holds the storage-options required by the ``fsspec`` backend of
    ``src``. Sensitive values (see :data:`SECRET_CREDENTIAL_KEYS`) are stored
    obfuscated in the configuration file and resolved from the host keyring at
    bind time.

    ``scope`` records which config file the dataloader was loaded from
    (``"global"`` by default; ``"local"`` for the current project's
    ``.qall.yml``).
    """

    name: str
    src: str
    dst: str
    creds: dict = field(default_factory=dict)
    scope: str = "global"

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


# Interactive credential prompt table, keyed by the ``fsspec`` protocol (scheme)
# of the dataloader ``src``. Each field mirrors the provider-login shape:
# ``{"name", "prompt", "hide_input"}`` where ``name`` is the fsspec-native
# credential key. Unknown schemes and local files need no credentials, so they
# map to an empty table (automation must pass flags for those backends).
_CREDENTIAL_FIELD_PROTOCOLS = {
    "s3": [
        {"name": "key", "prompt": "Access key", "hide_input": False},
        {"name": "secret", "prompt": "Secret key", "hide_input": True},
        {
            "name": "endpoint_url",
            "prompt": "Endpoint URL (optional)",
            "hide_input": False,
        },
    ],
    "s3a": [
        {"name": "key", "prompt": "Access key", "hide_input": False},
        {"name": "secret", "prompt": "Secret key", "hide_input": True},
        {
            "name": "endpoint_url",
            "prompt": "Endpoint URL (optional)",
            "hide_input": False,
        },
    ],
    "s3n": [
        {"name": "key", "prompt": "Access key", "hide_input": False},
        {"name": "secret", "prompt": "Secret key", "hide_input": True},
        {
            "name": "endpoint_url",
            "prompt": "Endpoint URL (optional)",
            "hide_input": False,
        },
    ],
}


def credential_fields_for_protocol(protocol: str) -> list[dict]:
    """
    Returns the interactive credential prompt fields for an object-storage
    protocol (URL scheme), mirroring the provider-login shape
    ``[{name, prompt, hide_input}, ...]``.

    Only protocols with a known prompt table are listed; ``file://`` and any
    unknown scheme return ``[]`` (no prompts, credentials via flags only).
    """
    return list(_CREDENTIAL_FIELD_PROTOCOLS.get((protocol or "").lower(), []))


### Mount-point normalisation (mirrored by the daemon) ###


def normalize_dst(dst: str) -> str:
    """
    Normalises a dataloader mount point into a safe *relative* path.

    ``"./my_data/"``, ``"my_data"`` and ``"/my_data/"`` are equivalent, and the
    daemon mounts the result at ``/<normalised>`` inside the task container
    (``dst="my_bucket"`` -> ``/my_bucket``). Empty targets, absolute-only
    targets (``"/"``) and ``..`` traversal are rejected.

    This is the single source of truth on the SDK side; the daemon implements
    the exact same rule in ``normalizeDst`` (Go) because it builds the mount
    target itself. Keep both in sync.
    """
    if dst is None or not str(dst).strip():
        raise ValueError("dataloader dst must not be empty.")
    norm = str(dst).replace("\\", "/").strip()
    while norm.startswith("./"):
        norm = norm[2:]
    norm = norm.strip("/")
    if not norm:
        raise ValueError(
            f"dataloader dst {dst!r} must point to a sub-directory, not the root."
        )
    parts = norm.split("/")
    if ".." in parts:
        raise ValueError(
            f"dataloader dst {dst!r} must not contain '..' path traversal."
        )
    norm = "/".join(p for p in parts if p not in ("", "."))
    if not norm:
        raise ValueError(f"dataloader dst {dst!r} normalized to an empty mount point.")
    return norm


def is_remote_src(src: str) -> bool:
    """
    Returns True when ``src`` targets a *remote* object storage (``s3://``,
    ``gs://``, ``az://``, ...), i.e. when binding it needs a kernel mount
    (rclone/FUSE) rather than a plain host bind mount.

    ``file://`` and bare local paths are not remote: the daemon bind-mounts them
    read-only without any host dependency.
    """
    scheme = (urlparse(src or "").scheme or "").lower()
    return bool(scheme) and scheme != "file"
