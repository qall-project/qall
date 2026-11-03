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
from qall.object import Dataloader, DATALOADER_SCOPES

from .local_config import LocalConfiguration
from .paths import CONFIG_PATH, QALL_CONFIG_DIR

logger = logging.getLogger(__name__)

# Keyring service used to store the plaintext of sensitive dataloader
# credentials. The keyring user is the scoped name ``"{scope}:{name}"`` so a
# local and a global dataloader can share a name without keyring collisions.
KEYRING_DATALOADER_SERVICE = "qall_dataloader"

# Obfuscation placeholder written into the config file for any sensitive
# credential key (see Dataloader.is_secret_key). The runtime resolves it back
# from the keyring, so plaintext secrets never hit the config file.
_KEYRING_PLACEHOLDER_PREFIX = f"keyring://{KEYRING_DATALOADER_SERVICE}/"

# Legacy (pre-scoping, JSON format) machine-wide config. Migrated once into the
# new global YAML (``CONFIG_PATH``) and then left in place (never deleted).
LEGACY_CONFIG_PATH = QALL_CONFIG_DIR / "qall-config.json"

# Default filename of the per-project (local) config file.
_DEFAULT_LOCAL_CONFIG_FILENAME = ".qall.yml"

# Conventioned mount point where the client provisions one resolved-secrets
# file per task (`<task_hash>.json`) that references dataloaders. The directory
# is bind-mounted read-only into every task container by the daemon, so the
# task runtime reads its dataloaders from here. Secrets never pass through the
# daemon's control plane nor appear in env vars / wrapper code.
#
# This is deliberately a TOP-LEVEL /tmp path, NOT a subdirectory of the
# daemon's token dir (/tmp/qall-secrets). The daemon runs as root and owns
# that token tree; a nested dataloaders subdirectory would be created root-owned
# (0700) and become unusable by the unprivileged client. Being its own
# client-owned directory, this path is never touched by the daemon.
_DEFAULT_DATALOADERS_SECRETS_DIR = Path("/tmp/qall-dataloaders")

# Permissions of the secrets directory (0700) and of each secrets file (0400).
_SECRETS_DIR_MODE = 0o700
_SECRETS_FILE_MODE = 0o400


def normalize_scope(scope: str) -> str:
    """Validates a dataloader config scope identifier."""
    if scope not in DATALOADER_SCOPES:
        raise ValueError(
            f"Unknown dataloader config scope {scope!r}. "
            f"Expected one of {DATALOADER_SCOPES}."
        )
    return scope


def global_config_path() -> Path:
    """Path of the machine-wide (global) config file (env-overridable)."""
    override = os.environ.get("QALL_CONFIG_PATH")
    return Path(override) if override else CONFIG_PATH


def local_config_path() -> Path:
    """Path of the current-project config file (env-overridable)."""
    override = os.environ.get("QALL_LOCAL_CONFIG_PATH")
    return Path(override) if override else Path(_DEFAULT_LOCAL_CONFIG_FILENAME)


def get_config_path() -> Path:
    """Backward-compatible alias for the global config path."""
    return global_config_path()


def config_path_for_scope(scope: str) -> Path:
    """Resolves a scope identifier to its config file path."""
    scope = normalize_scope(scope)
    if scope == "local":
        return local_config_path()
    return global_config_path()


def legacy_config_path() -> Path:
    """Path of the legacy (JSON) global config file, if any."""
    return LEGACY_CONFIG_PATH


def migrate_legacy_global_config() -> Optional[Path]:
    """
    Best-effort one-time migration of the legacy JSON global config
    (``qall-config.json``) into the new global YAML (``qall-config.yml``).

    Sensitive keyring entries are re-keyed from the legacy user ``<name>`` to
    the scoped user ``global:<name>`` and placeholders are rewritten
    accordingly. The legacy file is **left in place** and the migration runs at
    most once (it is skipped as soon as the global YAML exists).

    Returns the written global YAML path, or ``None`` when there is nothing to
    migrate (either the global YAML already exists, no legacy file was found,
    or the legacy file could not be read).
    """
    global_path = global_config_path()
    if global_path.exists():
        return None

    legacy = legacy_config_path()
    if not legacy.exists():
        return None

    try:
        with legacy.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Could not read legacy dataloader config {legacy}: {e}")
        return None

    dataloaders = data.get("dataloaders", {}) if isinstance(data, dict) else {}
    if not dataloaders:
        save_config({"dataloaders": {}})
        logger.info(
            f"Legacy config {legacy} holds no dataloaders; bootstrapped empty "
            f"global config at {global_path}"
        )
        return global_path

    migrated: dict = {}
    for name, entry in dataloaders.items():
        if not isinstance(entry, dict):
            continue
        creds = dict(entry.get("creds", {}) or {})
        # Re-key the legacy keyring entry (stored under user == name) under the
        # scoped user so the rewritten placeholders stay resolvable.
        legacy_secrets = get_token(KEYRING_DATALOADER_SERVICE, name)
        if isinstance(legacy_secrets, dict) and legacy_secrets:
            set_token(KEYRING_DATALOADER_SERVICE, f"global:{name}", legacy_secrets)
        migrated[name] = {
            "src": entry.get("src", ""),
            "dst": entry.get("dst", ""),
            "creds": obfuscate_creds("global", name, creds),
        }

    save_config({"dataloaders": migrated})
    logger.info(
        f"Migrated {len(migrated)} dataloader(s) from legacy config {legacy} "
        f"into {global_path}"
    )
    return global_path


def ensure_config(scope: str = "global") -> Path:
    """
    Transparently bootstraps the requested scope's config file if it does not
    exist yet. Idempotent and called from every CLI/core entry point so users
    never have to run an explicit ``init``.
    """
    scope = normalize_scope(scope)
    if scope == "global":
        migrated = migrate_legacy_global_config()
        if migrated is not None:
            return migrated

    path = config_path_for_scope(scope)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    save_config({"dataloaders": {}}, scope)
    logger.info(f"Bootstrapped qall config ({scope}) at {path}")
    return path


def load_config(scope: str = "global") -> dict:
    """Loads the target scope's config as a dict (empty layout if absent)."""
    scope = normalize_scope(scope)
    path = config_path_for_scope(scope)
    if not path.exists():
        return {"dataloaders": {}}
    cfg = LocalConfiguration.from_yaml_file(path)
    data = cfg.to_dict()
    data.setdefault("dataloaders", {})
    return data


def save_config(data: dict, scope: str = "global") -> Path:
    """Atomically writes the target scope's config back to disk as YAML."""
    scope = normalize_scope(scope)
    path = config_path_for_scope(scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = LocalConfiguration.from_dict(data)
    tmp = path.with_suffix(".tmp")
    cfg.to_yaml_file(tmp)
    tmp.replace(path)
    return path


def is_keyring_placeholder(value) -> bool:
    return isinstance(value, str) and value.startswith(_KEYRING_PLACEHOLDER_PREFIX)


def _keyring_user(scope: str, name: str) -> str:
    return f"{scope}:{name}"


def obfuscate_creds(scope: str, name: str, creds: dict) -> dict:
    """
    Maps a creds dict to its persisted form: sensitive values become keyring
    placeholders (scoped by ``scope:name``), everything else stays plaintext.
    """
    return {
        key: (
            f"{_KEYRING_PLACEHOLDER_PREFIX}{scope}:{name}/{key}"
            if Dataloader.is_secret_key(key)
            else value
        )
        for key, value in creds.items()
    }


def store_secrets(scope: str, name: str, creds: dict) -> None:
    """Persists the plaintext of sensitive creds into the host keyring."""
    secrets = {k: v for k, v in creds.items() if Dataloader.is_secret_key(k)}
    if secrets:
        set_token(KEYRING_DATALOADER_SERVICE, _keyring_user(scope, name), secrets)
        logger.info(
            f"Stored {len(secrets)} sensitive credential(s) for dataloader "
            f"{name!r} (scope {scope}) in keyring"
        )


def resolve_secrets(dl: Dataloader) -> dict:
    """
    Resolves the dataloader's full creds dict, replacing keyring placeholders
    with the plaintext stored on the host keyring.

    Fails loudly (``RuntimeError``) when a placeholder cannot be resolved, so a
    missing/obfuscated secret is never silently shipped to the runtime.
    """
    user = _keyring_user(dl.scope or "global", dl.name)
    try:
        stored = get_token(KEYRING_DATALOADER_SERVICE, user)
    except Exception as e:
        stored = None
        keyring_error = e
    else:
        keyring_error = None

    if not isinstance(stored, dict):
        # Also accept the legacy pre-scoping keyring user (plain name) so
        # non-migrated placeholder leftovers still resolve.
        try:
            legacy = get_token(KEYRING_DATALOADER_SERVICE, dl.name)
        except Exception:
            legacy = None
        if isinstance(legacy, dict):
            stored = legacy

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
            f"dataloader {dl.name!r} (scope {dl.scope!r}) from the host "
            f"keyring{detail}. Re-run `qall dataloader update --<key>=... "
            f"{dl.name}` to store them again (add `--current-project` if the "
            "dataloader is project-scoped)."
        )
    return merged


def delete_secrets(scope: str, name: str) -> None:
    """Removes the dataloader's secrets from the host keyring."""
    delete_token(KEYRING_DATALOADER_SERVICE, _keyring_user(scope, name))


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
