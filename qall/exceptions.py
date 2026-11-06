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
"""Hierarchical, actionable exceptions raised by the qall SDK.

This module deliberately imports nothing from :mod:`qall` so it can be imported
from every layer (objects, core, daemon helpers and the CLI) without creating a
circular import. Every exception carries an optional human-readable ``hint``
explaining what the user can do about the failure; :meth:`QallError.__str__`
appends it as a ``Hint: ...`` line.
"""

from __future__ import annotations


class QallError(Exception):
    """Base class for every qall-specific exception.

    ``message`` is the short description of what went wrong; ``hint`` is an
    optional, actionable explanation of how to fix it. Both are exposed as
    attributes so callers can format them independently.
    """

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message}\nHint: {self.hint}"
        return self.message


class DataloaderError(QallError):
    """Base class for every dataloader-related failure."""


class DataloaderConfigError(DataloaderError):
    """A dataloader definition is invalid or cannot be persisted/read."""


class DataloaderDependencyError(DataloaderError):
    """A host dependency is missing or invalid (Docker, FUSE, rclone plugin)."""


class DataloaderMountError(DataloaderError):
    """The daemon failed to create or mount a dataloader volume."""


# Daemon gRPC ``errdetails.ErrorInfo.Reason`` strings mapped to the exception the
# SDK should raise. The daemon always reports a structured reason so the client
# can branch on it instead of parsing an error message.
DATALOADER_ERROR_REASONS: dict[str, type[DataloaderError]] = {
    "QALL_DATALOADER_DEPENDENCY_MISSING": DataloaderDependencyError,
    "QALL_DATALOADER_TIMEOUT": DataloaderMountError,
    "QALL_DATALOADER_MOUNT_FAILED": DataloaderMountError,
}


def exception_for_reason(
    reason: str | None,
    message: str,
    hint: str | None = None,
) -> DataloaderError:
    """Builds the typed exception matching a daemon ``ErrorInfo.Reason``.

    Unknown or missing reasons default to :class:`DataloaderMountError`, since
    an unmapped dataloader error still originates from volume creation/mounting.
    """
    exception_class = DATALOADER_ERROR_REASONS.get(reason or "", DataloaderMountError)
    return exception_class(message, hint=hint)


__all__ = [
    "QallError",
    "DataloaderError",
    "DataloaderConfigError",
    "DataloaderDependencyError",
    "DataloaderMountError",
    "DATALOADER_ERROR_REASONS",
    "exception_for_reason",
]
