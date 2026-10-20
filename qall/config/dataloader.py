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
import logging
import os

from pathlib import Path
from typing import Optional

from qall.credential import set_token, get_token, delete_token
from qall.object import Dataloader

from .paths import CONFIG_PATH

logger = logging.getLogger(__name__)

# Keyring service used to store the plaintext of sensitive dataloader
# credentials. The user = dataloader name.
KEYRING_DATALOADER_SERVICE = "qall_dataloader"

# Obfuscation placeholder written into qall-config.json for any sensitive
# credential key (see Dataloader.is_secret_key). The runtime resolves it back
# from the keyring, so plaintext secrets never hit the config file.
_KEYRING_PLACEHOLDER_PREFIX = f"keyring://{KEYRING_DATALOADER_SERVICE}/"

# Conventioned mount point where the client provisions one resolved-secrets
# file per task (`<task_hash>.json`) that references dataloaders. The directory
# is bind-mounted read-only into every task container by the daemon, so the
# task runtime reads its dataloaders from here. Secrets never pass through the
# daemon's control plane nor appear in env vars / wrapper code.
#
# This is deliberately a TOP-LEVEL /dev/shm path, NOT a subdirectory of the
# daemon's token dir (/dev/shm/qall-secrets). The daemon runs as root and owns
# that token tree; a nested dataloaders subdirectory would be created root-owned
# (0700) and become unusable by the unprivileged client. Being its own
# client-owned directory, this path is never touched by the daemon.
_DEFAULT_DATALOADERS_SECRETS_DIR = Path("/dev/shm/qall-dataloaders")

# Permissions of the secrets directory (0700) and of each secrets file (0400).
_SECRETS_DIR_MODE = 0o700
_SECRETS_FILE_MODE = 0o400


def get_config_path() -> Path:
    """Path of the project user config file (env-overridable for testing)."""
    override = os.environ.get("QALL_CONFIG_PATH")
    return Path(override) if override else CONFIG_PATH


def ensure_config() -> Path:
    """
    Transparently bootstraps the user config file (``qall-config.json``) if it
    does not exist yet. Idempotent and called from every CLI/core entry point so
    users never have to run an explicit ``init``.
    """
    path = get_config_path()
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    save_config({"dataloaders": {}})
    logger.info(f"Bootstrapped qall user config at {path}")
    return path


def load_config() -> dict:
    """Loads the user config as a dict (empty layout if the file is absent)."""
    path = get_config_path()
    if not path.exists():
        return {"dataloaders": {}}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("dataloaders", {})
    return data


def save_config(data: dict) -> Path:
    """Atomically writes the user config back to disk."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def is_keyring_placeholder(value) -> bool:
    return isinstance(value, str) and value.startswith(_KEYRING_PLACEHOLDER_PREFIX)


def obfuscate_creds(name: str, creds: dict) -> dict:
    """
    Maps a creds dict to its persisted form: sensitive values become keyring
    placeholders, everything else stays plaintext.
    """
    return {
        key: (
            f"{_KEYRING_PLACEHOLDER_PREFIX}{name}/{key}"
            if Dataloader.is_secret_key(key)
            else value
        )
        for key, value in creds.items()
    }


def store_secrets(name: str, creds: dict) -> None:
    """Persists the plaintext of sensitive creds into the host keyring."""
    secrets = {k: v for k, v in creds.items() if Dataloader.is_secret_key(k)}
    if secrets:
        set_token(KEYRING_DATALOADER_SERVICE, name, secrets)
        logger.info(
            f"Stored {len(secrets)} sensitive credential(s) for dataloader {name!r} in keyring"
        )


def resolve_secrets(dl: Dataloader) -> dict:
    """
    Resolves the dataloader's full creds dict, replacing keyring placeholders
    with the plaintext stored on the host keyring.

    Fails loudly (``RuntimeError``) when a placeholder cannot be resolved, so a
    missing/obfuscated secret is never silently shipped to the runtime.
    """
    try:
        stored = get_token(KEYRING_DATALOADER_SERVICE, dl.name)
    except Exception as e:
        stored = None
        keyring_error = e
    else:
        keyring_error = None
    stored = stored if isinstance(stored, dict) else {}

    merged = dict(dl.creds)
    unresolved = []
    for key, value in merged.items():
        if is_keyring_placeholder(value):
            secret_key = value.rsplit("/", 1)[-1]
            if secret_key in stored:
                merged[key] = stored[secret_key]
            else:
                unresolved.append(key)

    if unresolved:
        detail = f" ({keyring_error})" if keyring_error else ""
        raise RuntimeError(
            f"Could not resolve sensitive credential(s) {unresolved} for "
            f"dataloader {dl.name!r} from the host keyring{detail}. Re-run "
            "`qall dataloader update --<key>=... <name>` to store them again."
        )
    return merged


def delete_secrets(name: str) -> None:
    """Removes the dataloader's secrets from the host keyring."""
    delete_token(KEYRING_DATALOADER_SERVICE, name)


### Task-secrets provisioning (shared mount) ###


def dataloaders_secrets_dir() -> Path:
    """
    Root directory holding one resolved-secrets file per task that references
    dataloaders. Env-overridable (``QALL_DATALOADERS_DIR``) for testing and for
    non-standard container layouts.
    """
    override = os.environ.get("QALL_DATALOADERS_DIR")
    return Path(override) if override else _DEFAULT_DATALOADERS_SECRETS_DIR


def dataloader_secrets_path(task_hash: str) -> Path:
    """Path of the resolved-secrets file for a given task hash."""
    return dataloaders_secrets_dir() / f"{task_hash}.json"


def write_dataloader_secrets(task_hash: str, specs: dict) -> Path:
    """
    Atomically writes the resolved dataloader specs of a task to the shared
    mount (dir ``0700``, file ``0400``). ``specs`` maps each dataloader name to
    ``{"src": ..., "dst": ..., "creds": {resolved...}}``.
    """
    path = dataloader_secrets_path(task_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, _SECRETS_DIR_MODE)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(specs, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, _SECRETS_FILE_MODE)
    tmp.replace(path)
    logger.info(f"Provisioned dataloader secrets for task {task_hash} at {path}")
    return path


def read_dataloader_secrets(task_hash: str) -> Optional[dict]:
    """
    Reads the resolved dataloader specs provisioned for ``task_hash``, or
    ``None`` when no such file exists (e.g. daemonless path, or task without
    dataloaders).
    """
    path = dataloader_secrets_path(task_hash)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def cleanup_dataloader_secrets(paths) -> None:
    """Best-effort removal of the given provisioned secrets files."""
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as e:
            logger.warning(f"Failed to remove dataloader secrets {path}: {e}")
