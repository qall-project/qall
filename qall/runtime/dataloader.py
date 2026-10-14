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
Pure-Python virtual filesystem binding for dataloaders.

Binds an arbitrary object storage (``s3://``, ``gcs://``, ``adl://``,
``file://``, ...) as a POSIX-compatible mount point *without* any kernel/FUSE
dependency: a small stdlib I/O shim transparently redirects every ``dst``-rooted
path opened by a task (``open``, ``Path``, ``glob``, ``os.*``, ...) to the
underlying ``fsspec`` filesystem, so the task code keeps using plain Python.

Security model:
  * each mount's fsspec fs is wrapped in a :class:`fsspec.implementations.dirfs.DirFileSystem`
    rooted at the ``src`` bucket/prefix, so code can never reach storage outside ``src``;
  * ``dst`` is normalized to a safe relative path (absolute / ``..`` rejected at bind time);
  * every intercepted path is abspath+realpath-resolved and must stay inside its mount root —
    ``open("mnist/../../etc/passwd")``-style traversals are refused;
  * credentials never appear in task source or logs.
"""

from __future__ import annotations

import builtins
import glob as _glob
import io
import logging
import os
import pathlib

from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urlparse

import fsspec
from fsspec.implementations.dirfs import DirFileSystem

from qall.config.paths import TASK_RUNTIME_WORKDIR

logger = logging.getLogger(__name__)


class DataloaderBindingError(RuntimeError):
    """Raised when a dataloader cannot be bound or used safely."""


class DataloaderPathTraversalError(DataloaderBindingError):
    """Raised when a task path escapes its dataloader mount root."""


_DEFAULT_SANDBOX_ROOT = TASK_RUNTIME_WORKDIR / "dataloaders"

# Registry of active mounts: absolute mount root -> fsspec filesystem.
_MOUNTS: dict[Path, fsspec.AbstractFileSystem] = {}

# Idempotency guard for the global stdlib shims.
_INSTALLED = False

# Originals captured before shimming, restored by reset().
_ORIG: dict[str, object] = {}
# Restoration metadata: name -> (holder, attr, original) used by reset().
_RESET: dict[str, tuple] = {}

# The original pathlib.Path class (our module binds it before any monkeypatch).
_ORIG_PATH = pathlib.Path


### Path helpers ###


def _is_within(root: Path, path: Path) -> bool:
    return path == root or root in path.parents


def _resolve(path) -> Optional[tuple[Path, fsspec.AbstractFileSystem, str]]:
    """
    Resolves ``path`` against the active mounts.

    Returns ``(mount_root, fs, rel_path)`` when the *resolved* path lives under a
    mount root, or ``None`` (plain local path) otherwise. Refuses a path whose raw
    form starts inside a mount root but resolves outside of it (traversal).
    """
    raw = Path(os.fspath(path)) if not isinstance(path, int) else None
    if raw is None:
        # Not a path (e.g. an open file descriptor): never a dataloader mount.
        return None
    abs_raw = raw if raw.is_absolute() else Path(os.getcwd()) / raw
    resolved = Path(os.path.realpath(abs_raw))

    for root, fs in _MOUNTS.items():
        if _is_within(root, resolved):
            rel = resolved.relative_to(root).as_posix()
            if rel == ".":
                # The mount root itself: object storages reject "." as a path
                # component (e.g. s3fs raises on ls(".")), so use the fs root.
                rel = ""
            return root, fs, rel
        if _is_within(root, abs_raw) and not _is_within(root, resolved):
            raise DataloaderPathTraversalError(
                f"Path {str(raw)!r} resolves to {str(resolved)!r}, outside "
                f"dataloader mount root {str(root)!r}: path traversal refused."
            )
    return None


def _resolve_glob(path) -> Optional[tuple[Path, fsspec.AbstractFileSystem, str]]:
    """
    Like :func:`_resolve` but for glob patterns: the static (non-magic) prefix is
    used for mount matching, and the whole pattern is returned relative to the fs
    root. ``None`` means the pattern does not target a mount.
    """
    raw = Path(os.fspath(path))
    abs_raw = raw if raw.is_absolute() else Path(os.getcwd()) / raw
    prefix = _static_prefix(abs_raw)

    for root, fs in _MOUNTS.items():
        if _is_within(root, prefix):
            rel = abs_raw.relative_to(root).as_posix()
            if rel == ".":
                rel = ""
            return root, fs, rel
    return None


def _static_prefix(pattern: Path) -> Path:
    """Returns the leading part of ``pattern`` that contains no glob magic."""
    parts = []
    for part in pattern.parts:
        if any(ch in part for ch in "*?["):
            break
        parts.append(part)
    return Path(*parts)


def _normalize_dst(dst: str) -> str:
    """
    Normalizes a mount point into a safe relative path.

    ``"./my_data/"``, ``"my_data"`` and ``"/my_data/"`` are equivalent (relative,
    per spec). Absolute targets, empty targets and ``..`` traversal are rejected.
    """
    if not dst:
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
        raise DataloaderPathTraversalError(
            f"dataloader dst {dst!r} must not contain '..' path traversal."
        )
    norm = "/".join(p for p in parts if p not in ("", "."))
    if not norm:
        raise ValueError(f"dataloader dst {dst!r} normalized to an empty mount point.")
    return norm


### fsspec construction ###


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
    task code can never reach storage outside ``src``.
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
    creation time). Never logs credentials.
    """
    try:
        fs = build_fs(src, secrets)
        fs.ls("")
        logger.info(f"Dataloader source {src} is reachable.")
        return True
    except Exception as e:
        logger.warning(f"Dataloader source {src} is not reachable: {e}")
        return False


### Binding ###


def bind_dataloader(
    name: str,
    src: str,
    dst: str,
    secrets: Optional[dict] = None,
    # sandbox_root: Optional[Path] = None,
) -> Path:
    """Binds a single dataloader as a virtual mount under ``sandbox_root``."""
    _install_shims()

    # if sandbox_root is None:
    #     sandbox_root = Path(os.getcwd())
    # sandbox_root = Path(sandbox_root).resolve()
    if not _DEFAULT_SANDBOX_ROOT.exists():
        _DEFAULT_SANDBOX_ROOT.mkdir()

    dst_rel = _normalize_dst(dst)
    mount_root = _DEFAULT_SANDBOX_ROOT / dst_rel
    mount_root.mkdir(parents=True, exist_ok=True)

    fs = build_fs(src, secrets)
    _MOUNTS[mount_root] = fs
    logger.info(f"Bound dataloader {name!r}: {src} -> {dst_rel} ({mount_root})")
    return mount_root


def bind_dataloaders(specs) -> None:
    """
    Binds a list of dataloader specs. Each spec is a mapping with ``name``,
    ``src``, ``dst`` and optional ``secrets`` (already resolved).
    """
    for spec in specs:
        bind_dataloader(
            name=spec["name"],
            src=spec["src"],
            dst=spec["dst"],
            secrets=spec.get("secrets"),
            # sandbox_root=sandbox_root,
        )


def unbind_dataloaders() -> None:
    """Clears all active mounts (shims stay installed)."""
    _MOUNTS.clear()
    logger.info("Unbound all dataloaders.")


def reset() -> None:
    """Restores all original stdlib functions/classes (test hook)."""
    global _INSTALLED
    for _holder, _attr, _orig in _RESET.values():
        try:
            setattr(_holder, _attr, _orig)
        except Exception:
            pass
    _ORIG.clear()
    _RESET.clear()
    _MOUNTS.clear()
    _INSTALLED = False
    logger.info("Restored original stdlib I/O functions.")


### stat helpers ###


def _ts(info: dict, key: str = "mtime") -> float:
    """
    Best-effort numeric timestamp from an fsspec ``info`` dict.

    ``LocalFileSystem`` reports ``mtime`` directly, but object storages (e.g.
    ``s3fs``) only expose ``LastModified`` (a ``datetime``); with no ``mtime``
    key the shim's ``os.path.getmtime``/``stat`` would otherwise raise or yield
    0. Falls back to ``0.0`` when no usable timestamp is present.
    """
    value = info.get(key)
    if value is None:
        value = info.get("mtime") if key != "mtime" else None
    if value is None and "LastModified" in info:
        value = info["LastModified"]
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _stat_from_info(info: dict) -> os.stat_result:
    ftype = info.get("type", "file")
    mode = 0o100644 if ftype == "file" else 0o040755
    return os.stat_result(
        (
            mode,
            info.get("inode", 0),
            0,  # st_dev
            1,  # st_nlink
            0,  # st_uid
            0,  # st_gid
            info.get("size", 0),
            int(_ts(info)),
            int(_ts(info)),
            int(_ts(info, "ctime")),
        )
    )


### I/O shims ###


class _DirEntry:
    """Minimal :class:`os.DirEntry`-compatible object backed by fsspec info."""

    def __init__(self, name: str, path: str, info: dict):
        self.name = name
        self.path = path
        self._info = info

    def is_dir(self, follow_symlinks: bool = True) -> bool:
        return self._info.get("type") == "directory"

    def is_file(self, follow_symlinks: bool = True) -> bool:
        return self._info.get("type") == "file"

    def is_symlink(self) -> bool:
        return False

    def stat(self, follow_symlinks: bool = True) -> os.stat_result:
        return _stat_from_info(self._info)

    def inode(self) -> int:
        return self._info.get("inode", 0)

    def __repr__(self):
        return f"<DirEntry {self.path!r}>"


class _ScandirIterator(Iterator):
    """Iterator with ``close()`` and context-manager support (os.scandir API)."""

    def __init__(self, entries):
        self._it = iter(entries)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._it)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _qall_open(
    file,
    mode="r",
    buffering=-1,
    encoding=None,
    errors=None,
    newline=None,
    **kwargs,
):
    hit = _resolve(file)
    if hit is not None:
        _root, fs, rel = hit
        fkwargs = dict(kwargs)
        fkwargs.pop("opener", None)
        fkwargs.pop("closefd", None)
        if encoding is not None:
            fkwargs["encoding"] = encoding
        if errors is not None:
            fkwargs["errors"] = errors
        if newline is not None:
            fkwargs["newline"] = newline
        if any(ch in mode for ch in "wax+") and rel:
            dirname = rel.rsplit("/", 1)[0] if "/" in rel else ""
            if dirname:
                fs.makedirs(dirname, exist_ok=True)
        return fs.open(rel, mode, **fkwargs)
    return _ORIG["open"](
        file,
        mode,
        buffering=buffering,
        encoding=encoding,
        errors=errors,
        newline=newline,
        **kwargs,
    )


def _qall_listdir(path="."):
    hit = _resolve(path)
    if hit is None:
        return _ORIG["listdir"](path)
    _root, fs, rel = hit
    entries = fs.ls(rel, detail=False)
    names = []
    prefix = rel + "/" if rel else ""
    for entry in entries:
        e = str(entry).lstrip("/")
        if prefix:
            if not e.startswith(prefix):
                continue
            name = e[len(prefix) :]
        else:
            name = e.split("/", 1)[0]
        if name and "/" not in name:
            names.append(name)
    return sorted(set(names))


def _qall_scandir(path="."):
    hit = _resolve(path)
    if hit is None:
        return _ORIG["scandir"](path)
    root, fs, rel = hit
    details = fs.ls(rel, detail=True)
    prefix = rel + "/" if rel else ""
    entries = []
    for d in details:
        full = str(d.get("name", "")).lstrip("/")
        if prefix:
            if not full.startswith(prefix):
                continue
            name = full[len(prefix) :]
        else:
            name = full.split("/", 1)[0]
        if not name or "/" in name:
            continue
        info = {
            "type": d.get("type", "file"),
            "size": d.get("size", 0),
            "mtime": d.get("mtime", 0),
            "inode": d.get("inode", 0),
        }
        entries.append(_DirEntry(name, os.path.join(str(root), name), info))
    return _ScandirIterator(entries)


def _qall_stat(path, *args, **kwargs):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        return _stat_from_info(fs.info(rel))
    return _ORIG["stat"](path, *args, **kwargs)


def _qall_mkdir(path, mode=0o777, *args, **kwargs):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        fs.mkdir(rel, create_parents=False)
        return
    return _ORIG["mkdir"](path, mode, *args, **kwargs)


def _qall_makedirs(path, mode=0o777, exist_ok=False):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        fs.makedirs(rel, exist_ok=exist_ok)
        return
    return _ORIG["makedirs"](path, mode, exist_ok=exist_ok)


def _qall_remove(path, *args, **kwargs):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        fs.rm(rel)
        return
    return _ORIG["remove"](path, *args, **kwargs)


def _qall_unlink(path, *args, **kwargs):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        fs.rm(rel)
        return
    return _ORIG["unlink"](path, *args, **kwargs)


def _qall_rmdir(path, *args, **kwargs):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        fs.rmdir(rel)
        return
    return _ORIG["rmdir"](path, *args, **kwargs)


def _qall_rename(src, dst, *args, **kwargs):
    hit_src = _resolve(src)
    hit_dst = _resolve(dst)
    if hit_src is None and hit_dst is None:
        return _ORIG["rename"](src, dst, *args, **kwargs)
    if hit_src is None or hit_dst is None or hit_src[1] is not hit_dst[1]:
        raise OSError(
            "os.rename across dataloader filesystem boundaries is not supported."
        )
    _root, fs, rel_src = hit_src
    _r2, _f2, rel_dst = hit_dst
    fs.mv(rel_src, rel_dst)


def _path_op_remote(fs, rel, name, default):
    try:
        method = getattr(fs, name)
        return method(rel)
    except FileNotFoundError:
        return default
    except OSError:
        return default


def _qall_path_exists(path):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        return _path_op_remote(fs, rel, "exists", False)
    return _ORIG["path_exists"](path)


def _qall_path_isfile(path):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        return _path_op_remote(fs, rel, "isfile", False)
    return _ORIG["path_isfile"](path)


def _qall_path_isdir(path):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        return _path_op_remote(fs, rel, "isdir", False)
    return _ORIG["path_isdir"](path)


def _qall_path_getsize(path):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        return int(fs.info(rel)["size"])
    return _ORIG["path_getsize"](path)


def _qall_path_getmtime(path):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        return _ts(fs.info(rel))
    return _ORIG["path_getmtime"](path)


def _qall_path_getatime(path):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        return _ts(fs.info(rel))
    return _ORIG["path_getatime"](path)


def _qall_path_getctime(path):
    hit = _resolve(path)
    if hit is not None:
        _root, fs, rel = hit
        return _ts(fs.info(rel), "ctime")
    return _ORIG["path_getctime"](path)


def _qall_glob(pathname, *, recursive=False, include_hidden=True):
    pathname = os.fspath(pathname)
    hit = _resolve_glob(pathname)
    if hit is None:
        return _ORIG["glob"](
            pathname, recursive=recursive, include_hidden=include_hidden
        )

    root, fs, rel = hit
    if "**" in rel and not recursive:
        rel = rel.replace("**", "*")
    matches = fs.glob(rel)
    results = []
    for m in matches:
        match_abs = root / m
        if os.path.isabs(pathname):
            results.append(str(match_abs))
        else:
            results.append(os.path.relpath(str(match_abs), os.getcwd()))
    return results


def _qall_iglob(pathname, *, recursive=False, include_hidden=True):
    return iter(
        _qall_glob(pathname, recursive=recursive, include_hidden=include_hidden)
    )


### pathlib shim ###


class QallPath(_ORIG_PATH):
    """A :class:`pathlib.Path` that routes mount-rooted operations to fsspec."""

    def _hit(self):
        return _resolve(self)

    def open(self, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        return _qall_open(
            self,
            mode,
            buffering=buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
        )

    def read_bytes(self):
        with self.open("rb") as f:
            return f.read()

    def read_text(self, encoding=None, errors=None, newline=None):
        with self.open("r", encoding=encoding, errors=errors, newline=newline) as f:
            return f.read()

    def write_bytes(self, data):
        with self.open("wb") as f:
            return f.write(data)

    def write_text(self, data, encoding=None, errors=None, newline=None):
        if not isinstance(data, str):
            raise TypeError("data must be str, not %s" % data.__class__.__name__)
        with self.open("w", encoding=encoding, errors=errors, newline=newline) as f:
            return f.write(data)

    def exists(self):
        hit = _resolve(self)
        if hit is not None:
            _root, fs, rel = hit
            return _path_op_remote(fs, rel, "exists", False)
        return super().exists()

    def is_file(self):
        hit = _resolve(self)
        if hit is not None:
            _root, fs, rel = hit
            return _path_op_remote(fs, rel, "isfile", False)
        return super().is_file()

    def is_dir(self):
        hit = _resolve(self)
        if hit is not None:
            _root, fs, rel = hit
            return _path_op_remote(fs, rel, "isdir", False)
        return super().is_dir()

    def stat(self, *, follow_symlinks=True):
        hit = _resolve(self)
        if hit is not None:
            _root, fs, rel = hit
            return _stat_from_info(fs.info(rel))
        return super().stat(follow_symlinks=follow_symlinks)

    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        hit = _resolve(self)
        if hit is not None:
            _root, fs, rel = hit
            if parents:
                fs.makedirs(rel, exist_ok=exist_ok)
            else:
                fs.mkdir(rel, create_parents=False)
            return
        return super().mkdir(mode=mode, parents=parents, exist_ok=exist_ok)

    def unlink(self, missing_ok=False):
        hit = _resolve(self)
        if hit is not None:
            _root, fs, rel = hit
            if not missing_ok:
                fs.rm(rel)
            else:
                try:
                    fs.rm(rel)
                except FileNotFoundError:
                    pass
            return
        return super().unlink(missing_ok=missing_ok)

    def rmdir(self):
        hit = _resolve(self)
        if hit is not None:
            _root, fs, rel = hit
            fs.rmdir(rel)
            return
        return super().rmdir()

    def rename(self, target):
        _qall_rename(self, target)
        return type(self)(target)

    def touch(self, mode=0o666, exist_ok=True):
        hit = _resolve(self)
        if hit is not None:
            _root, fs, rel = hit
            try:
                fs.touch(rel, truncate=True)
            except (NotImplementedError, OSError):
                if not exist_ok and _path_op_remote(fs, rel, "exists", False):
                    raise FileExistsError(f"File exists: {self}")
            return
        return super().touch(mode=mode, exist_ok=exist_ok)

    def glob(self, pattern):
        hit = _resolve_glob(self / pattern)
        if hit is not None:
            root, fs, rel = hit
            for m in fs.glob(rel):
                yield type(self)(root) / m
            return
        yield from super().glob(pattern)

    def rglob(self, pattern):
        hit = _resolve_glob(self / pattern)
        if hit is not None:
            root, fs, rel = hit
            for m in fs.glob(rel if rel.startswith("**") else "**/" + rel):
                yield type(self)(root) / m
            return
        yield from super().rglob(pattern)


### Installation ###


def _install_shims() -> None:
    """Installs the stdlib shims once per process (idempotent)."""
    global _INSTALLED
    if _INSTALLED:
        return

    def _save(name, holder, attr):
        _ORIG[name] = getattr(holder, attr)
        _RESET[name] = (holder, attr, getattr(holder, attr))

    _save("open", builtins, "open")
    _save("io_open", io, "open")
    for attr in (
        "listdir",
        "scandir",
        "stat",
        "mkdir",
        "makedirs",
        "remove",
        "unlink",
        "rmdir",
        "rename",
    ):
        _save(attr, os, attr)
    for attr in (
        "exists",
        "lexists",
        "isfile",
        "isdir",
        "getsize",
        "getmtime",
        "getatime",
        "getctime",
    ):
        _save(f"path_{attr}", os.path, attr)
    _save("glob", _glob, "glob")
    _save("glob.iglob", _glob, "iglob")
    _save("pathlib.Path", pathlib, "Path")

    builtins.open = _qall_open
    io.open = _qall_open
    os.listdir = _qall_listdir
    os.scandir = _qall_scandir
    os.stat = _qall_stat
    os.mkdir = _qall_mkdir
    os.makedirs = _qall_makedirs
    os.remove = _qall_remove
    os.unlink = _qall_unlink
    os.rmdir = _qall_rmdir
    os.rename = _qall_rename

    os.path.exists = _qall_path_exists
    os.path.lexists = _qall_path_exists
    os.path.isfile = _qall_path_isfile
    os.path.isdir = _qall_path_isdir
    os.path.getsize = _qall_path_getsize
    os.path.getmtime = _qall_path_getmtime
    os.path.getatime = _qall_path_getatime
    os.path.getctime = _qall_path_getctime

    _glob.glob = _qall_glob
    _glob.iglob = _qall_iglob

    pathlib.Path = QallPath

    _INSTALLED = True
    logger.info("Installed pure-Python dataloader I/O shims.")
