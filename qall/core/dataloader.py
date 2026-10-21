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
    write_dataloader_secrets,
    cleanup_dataloader_secrets,
)
from qall.runtime.dataloader import check_reachable

logger = logging.getLogger(__name__)


def init_dataloader_config() -> Path:
    """Transparently bootstraps the user config file (no-op if it exists)."""
    return ensure_config()


def add_dataloader(
    name: str,
    src: str,
    dst: str,
    creds: Optional[dict] = None,
    validate: bool = True,
) -> Dataloader:
    """Creates, validates and persists a new dataloader."""
    Dataloader.validate_name(name)
    creds = dict(creds or {})

    if not src or not dst:
        raise ValueError("dataloader 'src' and 'dst' are required.")

    dataloader = Dataloader(name=name, src=src, dst=dst, creds=creds)

    if validate and not check_reachable(src, creds):
        raise ValueError(
            f"Source {src!r} is not reachable with the provided credentials."
        )

    ensure_config()
    config = load_config()
    if name in config["dataloaders"]:
        raise ValueError(f"A dataloader named {name!r} already exists.")

    store_secrets(name, creds)
    config["dataloaders"][name] = {
        "src": src,
        "dst": dst,
        "creds": obfuscate_creds(name, creds),
    }
    save_config(config)

    logger.info(f"Added dataloader {name!r} ({src} -> {dst}).")
    return get_dataloader(name)


def update_dataloader(
    name: str,
    src: Optional[str] = None,
    dst: Optional[str] = None,
    creds: Optional[dict] = None,
    validate: bool = True,
) -> Dataloader:
    """Updates an existing dataloader (only provided fields are changed)."""
    current = get_dataloader(name)
    if current is None:
        raise ValueError(f"No dataloader named {name!r} found.")

    new_src = src if src is not None else current.src
    new_dst = dst if dst is not None else current.dst
    new_creds = dict(creds) if creds is not None else current.creds

    if validate and (src is not None or creds is not None):
        if not check_reachable(new_src, new_creds):
            raise ValueError(
                f"Source {new_src!r} is not reachable with the provided credentials."
            )

    if creds is not None:
        store_secrets(name, creds)
        new_creds = obfuscate_creds(name, creds)
    else:
        new_creds = current.creds

    config = load_config()
    config["dataloaders"][name] = {
        "src": new_src,
        "dst": new_dst,
        "creds": new_creds,
    }
    save_config(config)

    logger.info(f"Updated dataloader {name!r}.")
    return get_dataloader(name)


def remove_dataloader(name: str) -> bool:
    """Removes a dataloader (config entry + keyring secrets)."""
    config = load_config()
    if name not in config["dataloaders"]:
        return False
    del config["dataloaders"][name]
    save_config(config)
    delete_secrets(name)
    logger.info(f"Removed dataloader {name!r}.")
    return True


def list_dataloaders() -> list[Dataloader]:
    """Returns every persisted dataloader (obfuscated creds)."""
    config = load_config()
    result = []
    for name, entry in config["dataloaders"].items():
        result.append(
            Dataloader(
                name=name,
                src=entry["src"],
                dst=entry["dst"],
                creds=entry.get("creds", {}),
            )
        )
    return result


def get_dataloader(name: str) -> Optional[Dataloader]:
    """Returns a single dataloader or ``None``."""
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


### Task-secrets provisioning for the shared /dev/shm mount ###


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


def provision_dataloader_file_for_task(
    task_hash: str,
    registry,
    names: Optional[list[str]] = None,
) -> Optional[Path]:
    """
    Writes the resolved-secrets file for a single task. ``names`` may be passed
    explicitly (e.g. from a DAG node); otherwise the node's metadata is read
    from ``registry``. Returns ``None`` when the task references no dataloader.
    """
    if names is None:
        node = registry.get_node_from_local(hash=task_hash)
        if node is None:
            return None
        names = node.metadata.dataloaders
    if not names:
        return None
    return write_dataloader_secrets(task_hash, resolve_dataloader_specs(names))


def provision_dataloader_files_for_dag(dag) -> list[Path]:
    """
    Writes resolved-secrets files for every task node of a pushed workflow DAG
    that references dataloaders. Called by the client on the host before a
    ``--local`` run so each task container (entrypoint and subtasks) finds its
    own secrets at the conventioned mount path.
    """
    written: list[Path] = []
    for node in dag.nodes:
        names = node.metadata.dataloaders
        if not names:
            continue
        written.append(
            write_dataloader_secrets(node.hash, resolve_dataloader_specs(names))
        )
    return written


def cleanup_dataloader_files(paths) -> None:
    """Best-effort removal of previously provisioned secrets files."""
    cleanup_dataloader_secrets(paths)
