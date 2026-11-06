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

import logging

from pathlib import Path
from typing import Optional

from qall.object import Dataloader
from qall.config.dataloader import (
    ensure_config,
    load_config,
    save_config,
    store_secrets,
    delete_secrets,
    obfuscate_creds,
    resolve_secrets,
)
from qall.runtime.dataloader import check_reachable

logger = logging.getLogger(__name__)


def init_dataloader_config() -> Path:
    """Transparently bootstraps the global config file (no-op if it exists)."""
    return ensure_config("global")


def add_dataloader(
    name: str,
    src: str,
    dst: str,
    creds: Optional[dict] = None,
    validate: bool = True,
    scope: str = "global",
) -> Dataloader:
    """Creates, validates and persists a new dataloader."""
    Dataloader.validate_name(name)
    creds = dict(creds or {})

    if not src or not dst:
        raise ValueError("dataloader 'src' and 'dst' are required.")

    if validate and not check_reachable(src, creds):
        raise ValueError(
            f"Source {src!r} is not reachable with the provided credentials."
        )

    ensure_config(scope)
    config = load_config(scope)
    if name in config["dataloaders"]:
        raise ValueError(
            f"A dataloader named {name!r} already exists in the {scope} config."
        )
    if scope == "local" and name in load_config("global")["dataloaders"]:
        logger.info(
            f"Dataloader {name!r} also exists in the global config; the local "
            "entry will shadow it for this project."
        )

    store_secrets(scope, name, creds)
    config["dataloaders"][name] = {
        "src": src,
        "dst": dst,
        "creds": obfuscate_creds(scope, name, creds),
    }
    save_config(config, scope)

    logger.info(f"Added dataloader {name!r} ({src} -> {dst}) [{scope}].")
    return Dataloader(
        name=name,
        src=src,
        dst=dst,
        creds=config["dataloaders"][name]["creds"],
        scope=scope,
    )


def update_dataloader(
    name: str,
    src: Optional[str] = None,
    dst: Optional[str] = None,
    creds: Optional[dict] = None,
    validate: bool = True,
    scope: Optional[str] = None,
) -> Dataloader:
    """
    Updates an existing dataloader (only provided fields are changed).

    ``scope=None`` targets the effective dataloader (local first, then global).
    When ``creds`` is provided it is merged over the currently resolved
    plaintext values, so credential keys simply omitted (e.g. an empty prompt
    answer) keep their stored value.
    """
    current = get_dataloader(name)
    if current is None:
        raise ValueError(f"No dataloader named {name!r} found.")

    effective_scope = scope if scope is not None else current.scope
    if scope is not None and scope != current.scope:
        raise ValueError(f"No dataloader named {name!r} found in the {scope} config.")

    new_src = src if src is not None else current.src
    new_dst = dst if dst is not None else current.dst

    if creds is not None:
        # Merge the explicitly-provided plaintext over the currently resolved
        # values so prompts left empty keep the stored credential.
        stored_plain = resolve_secrets(current)
        merged_plain = {
            **stored_plain,
            **{k: v for k, v in creds.items() if v != ""},
        }
        if validate and not check_reachable(new_src, merged_plain):
            raise ValueError(
                f"Source {new_src!r} is not reachable with the provided credentials."
            )
        store_secrets(effective_scope, name, merged_plain)
        new_creds = obfuscate_creds(effective_scope, name, merged_plain)
    else:
        new_creds = current.creds
        if (
            validate
            and src is not None
            and not check_reachable(new_src, resolve_secrets(current))
        ):
            raise ValueError(
                f"Source {new_src!r} is not reachable with the provided credentials."
            )

    config = load_config(effective_scope)
    config["dataloaders"][name] = {
        "src": new_src,
        "dst": new_dst,
        "creds": new_creds,
    }
    save_config(config, effective_scope)

    logger.info(f"Updated dataloader {name!r} [{effective_scope}].")
    return Dataloader(
        name=name,
        src=new_src,
        dst=new_dst,
        creds=new_creds,
        scope=effective_scope,
    )


def remove_dataloader(name: str, scope: Optional[str] = None) -> bool:
    """
    Removes a dataloader (config entry + keyring secrets).

    ``scope=None`` removes the effective dataloader (local first, then global).
    """
    current = get_dataloader(name)
    if current is None:
        return False
    effective_scope = scope if scope is not None else current.scope
    if scope is not None and scope != current.scope:
        return False

    config = load_config(effective_scope)
    if name not in config["dataloaders"]:
        return False
    del config["dataloaders"][name]
    save_config(config, effective_scope)
    delete_secrets(effective_scope, name)
    logger.info(f"Removed dataloader {name!r} [{effective_scope}].")
    return True


def list_dataloaders() -> list[Dataloader]:
    """
    Returns every defined dataloader (obfuscated creds) across scopes, with
    local entries shadowing global ones of the same name.
    """
    merged: dict[str, Dataloader] = {}
    for scope in ("global", "local"):
        config = load_config(scope)
        for name, entry in config["dataloaders"].items():
            merged[name] = Dataloader(
                name=name,
                src=entry["src"],
                dst=entry["dst"],
                creds=entry.get("creds", {}),
                scope=scope,
            )
    return list(merged.values())


def get_dataloader(name: str) -> Optional[Dataloader]:
    """Returns a single dataloader (local first, then global) or ``None``."""
    for dl in list_dataloaders():
        if dl.name == name:
            return dl
    return None


def get_dataloaders_for_names(names: list[str]) -> list[Dataloader]:
    """Resolves dataloader names referenced by a task into their DTOs."""
    by_name = {dl.name: dl for dl in list_dataloaders()}
    resolved = []
    for name in names:
        dl = by_name.get(name)
        if dl is None:
            raise ValueError(
                f"Task references dataloader {name!r} but no such dataloader is "
                "defined (see `qall dataloader add`)."
            )
        resolved.append(dl)
    return resolved


def validate_dataloader(name: str) -> bool:
    """Re-checks reachability of a dataloader with its resolved secrets."""
    dl = get_dataloader(name)
    if dl is None:
        raise ValueError(f"No dataloader named {name!r} found.")
    return check_reachable(dl.src, resolve_secrets(dl))


### Dataloader resolution for daemon task execution ###


def resolve_dataloader_specs(names: list[str]) -> dict:
    """
    Resolves dataloader names into the persisted mount-file layout
    ``{name: {"src": ..., "dst": ..., "creds": {resolved}}}`` with every
    keyring placeholder replaced by its plaintext. Raises ``ValueError`` when a
    referenced dataloader is not defined.
    """
    by_name = {dl.name: dl for dl in list_dataloaders()}
    specs: dict = {}
    for name in names:
        dl = by_name.get(name)
        if dl is None:
            raise ValueError(
                f"Task references dataloader {name!r} but no such dataloader is "
                "defined (see `qall dataloader add`)."
            )
        specs[name] = {
            "src": dl.src,
            "dst": dl.dst,
            "creds": resolve_secrets(dl),
        }
    return specs


def resolve_dataloaders_by_task(dag) -> list[dict]:
    """
    Resolves every dataloader referenced by a pushed workflow DAG into the flat
    list sent to the daemon on the run's root CreateTaskRunRequest:
    ``[{task_hash, name, src, dst, credentials}]``. ``credentials`` hold the
    plaintext resolved from the host keyring; the daemon writes each task's own
    entries into its per-task-run secrets file and mounts them into the task
    container. Tasks that reference no dataloader contribute no entries. Raises
    ``ValueError`` when a referenced dataloader is not defined.
    """
    entries: list[dict] = []
    for node in dag.nodes:
        names = node.metadata.dataloaders
        if not names:
            continue
        for name, spec in resolve_dataloader_specs(names).items():
            entries.append(
                {
                    "task_hash": node.hash,
                    "name": name,
                    "src": spec["src"],
                    "dst": spec["dst"],
                    "credentials": spec["creds"],
                }
            )
    return entries
