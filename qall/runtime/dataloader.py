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
"""
Client-side validation helpers for dataloaders.

Dataloaders are **mounted by the daemon**, not by the task process: on task-run
creation the daemon creates an rclone-backed Docker volume per
``(workflow_run_id, dataloader_name)`` and mounts it at ``/<dst>`` inside the
task container, so task code simply reads ``Path("/<dst>")`` through the kernel.
No stdlib monkeypatching, no in-process bootstrap.

This module therefore only answers the question a *client* can answer before
anything is pushed: "is this source reachable with these credentials?" It is
used by the `qall dataloader add/update/validate` commands (through
:func:`qall.core.dataloader.validate_dataloader`). Nothing here is imported by
the task container at runtime.
"""

from __future__ import annotations

import logging

from typing import Optional
from urllib.parse import urlparse

import fsspec
from fsspec.implementations.dirfs import DirFileSystem

logger = logging.getLogger(__name__)


def _src_root_path(src: str) -> str:
    parsed = urlparse(src)
    if not parsed.netloc and parsed.path.startswith("/"):
        # Absolute local path (e.g. file:///my/local/storage): the underlying
        # LocalFileSystem uses absolute POSIX paths, so keep the leading slash.
        return parsed.path.rstrip("/")
    # Object-storage root: bucket/container + optional prefix (e.g. s3://my/storage/).
    return f"{parsed.netloc}{parsed.path}".strip("/")


def build_fs(src: str, secrets: Optional[dict] = None) -> fsspec.AbstractFileSystem:
    """
    Builds an ``fsspec`` filesystem for ``src``, rooted at the bucket/prefix so
    callers can never reach storage outside ``src``.
    """
    parsed = urlparse(src)
    protocol = (parsed.scheme or "file").lower()
    fs = fsspec.filesystem(protocol, **(secrets or {}))
    root_path = _src_root_path(src)
    if root_path:
        fs = DirFileSystem(path=root_path, fs=fs)
    return fs


def check_reachable(src: str, secrets: Optional[dict] = None) -> bool:
    """
    Validates that ``src`` is reachable with ``secrets`` (used at dataloader
    creation/validation time, from the client side). Never logs credentials.
    """
    try:
        fs = build_fs(src, secrets)
        fs.ls("")
        logger.info(f"Dataloader source {src} is reachable.")
        return True
    except Exception as e:
        logger.warning(f"Dataloader source {src} is not reachable: {e}")
        return False
