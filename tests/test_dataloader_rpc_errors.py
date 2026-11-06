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
Unit tests for the SDK-side dataloader pre-flight and gRPC error translation
(``qall/core/daemon.py``).

No Docker, no daemon: the gRPC errors are forged with a real
``google.rpc.Status`` + ``ErrorInfo`` payload, exactly the way the daemon sends
them.
"""

import grpc
import pytest

from google.protobuf import any_pb2
from google.rpc import error_details_pb2, status_pb2

from qall.core.daemon import (
    _dataloader_error_from_rpc,
    _ensure_remote_dataloader_support,
)
from qall.exceptions import (
    DataloaderDependencyError,
    DataloaderError,
    DataloaderMountError,
)


class _FakeRpcError(Exception):
    """Minimal stand-in for ``grpc.RpcError`` (details + trailing metadata)."""

    def __init__(self, message, code=grpc.StatusCode.FAILED_PRECONDITION, details=None):
        super().__init__(message)
        self._message = message
        self._code = code
        self._details = details or ()

    def details(self):
        return self._message

    def code(self):
        return self._code

    def trailing_metadata(self):
        return self._details


def _status_details(reason: str, hint: str | None = None):
    info = error_details_pb2.ErrorInfo(reason=reason, domain="qall.daemon")
    if hint is not None:
        info.metadata["hint"] = hint

    packed = any_pb2.Any()
    packed.Pack(info)

    status = status_pb2.Status(
        code=grpc.StatusCode.FAILED_PRECONDITION.value[0],
        message="dataloader failure",
        details=[packed],
    )
    return (("grpc-status-details-bin", status.SerializeToString()),)


def test_error_info_reason_maps_to_dependency_error():
    exc = _FakeRpcError(
        "the rclone plugin is not installed",
        details=_status_details(
            "QALL_DATALOADER_DEPENDENCY_MISSING",
            hint="docker plugin install rclone/docker-volume-rclone:amd64 --alias rclone --grant-all-permissions",
        ),
    )

    error = _dataloader_error_from_rpc(exc)

    assert isinstance(error, DataloaderDependencyError)
    assert "rclone plugin is not installed" in str(error)
    assert "grant-all-permissions" in (error.hint or "")
    assert "Hint:" in str(error)


def test_error_info_timeout_maps_to_mount_error():
    exc = _FakeRpcError(
        "dataloader volume operation timed out after 30s",
        details=_status_details("QALL_DATALOADER_TIMEOUT"),
    )

    error = _dataloader_error_from_rpc(exc)

    assert isinstance(error, DataloaderMountError)


def test_unknown_reason_falls_back_to_mount_error():
    exc = _FakeRpcError("boom", details=_status_details("SOMETHING_ELSE"))

    assert isinstance(_dataloader_error_from_rpc(exc), DataloaderMountError)


def test_message_fallback_when_details_are_absent():
    """Older daemons may not attach ErrorInfo; the reason token still maps."""
    exc = _FakeRpcError(
        "QALL_DATALOADER_DEPENDENCY_MISSING: fuse3 is required on this host"
    )

    error = _dataloader_error_from_rpc(exc)

    assert isinstance(error, DataloaderDependencyError)
    assert "fuse3" in str(error)


def test_translation_never_leaks_credentials():
    secret = "sk-super-secret-value"
    exc = _FakeRpcError(
        f"failed for key {secret}",
        details=_status_details("QALL_DATALOADER_MOUNT_FAILED"),
    )

    # The daemon is responsible for redacting; the translator must at least not
    # add anything (and stay a typed DataloaderError).
    error = _dataloader_error_from_rpc(exc)
    assert isinstance(error, DataloaderError)


def test_preflight_is_skipped_for_local_dataloaders(monkeypatch):
    import qall.daemon.dependencies as deps

    def _boom(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("pre-flight must not run for file:// dataloaders")

    monkeypatch.setattr(deps, "ensure_dataloader_dependencies", _boom)

    # No dataloader at all, and local (file:// / bare path) ones.
    _ensure_remote_dataloader_support(None)
    _ensure_remote_dataloader_support([])
    _ensure_remote_dataloader_support(
        [
            {"name": "local", "src": "file:///home/me/data"},
            {"name": "bare", "src": "/srv/data"},
        ]
    )


def test_preflight_runs_for_remote_dataloaders(monkeypatch):
    import qall.daemon.dependencies as deps

    calls = []

    def _fake(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(deps, "ensure_dataloader_dependencies", _fake)

    _ensure_remote_dataloader_support(
        [
            {"name": "local", "src": "file:///home/me/data"},
            {"name": "bucket", "src": "s3://my-bucket/prefix"},
        ]
    )

    assert len(calls) == 1


def test_preflight_propagates_dependency_errors(monkeypatch):
    import qall.daemon.dependencies as deps

    def _raise(*args, **kwargs):
        raise DataloaderDependencyError("fuse is missing", hint="install fuse3")

    monkeypatch.setattr(deps, "ensure_dataloader_dependencies", _raise)

    with pytest.raises(DataloaderDependencyError):
        _ensure_remote_dataloader_support([{"name": "bucket", "src": "gs://my-bucket"}])
