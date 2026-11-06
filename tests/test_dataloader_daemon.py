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
Integration tests for dataloader v2: remote dataloaders are mounted by the
daemon as real kernel filesystems through the ``rclone`` Docker volume plugin.

Task code therefore sees the bucket at ``/<dst>`` (``dst="bucket"`` ->
``/bucket``) and reads/writes plain POSIX paths.

Requirements (the tests self-skip loudly when absent, and fail hard with
``-m daemon``):

1. the shared ``daemon_stack`` fixture (Docker + a locally built
   ``scw/qall-daemon:latest`` carrying this runtime API), *and*
2. ``fuse`` + the ``rclone`` Docker volume plugin on the host
   (``qall dataloader setup --check``), *and*
3. a reachable MinIO instance (``QALL_MINIO_ENDPOINT``, default
   ``http://127.0.0.1:9000``; ``QALL_MINIO_ACCESS_KEY``/``QALL_MINIO_SECRET_KEY``
   default to ``minioadmin``/``minioadmin``; ``QALL_MINIO_BUCKET`` default
   ``qall-dataloader-tests``).
"""

import os
import socket
import time
import uuid

from urllib.parse import urlparse

import pytest

MINIO_ENDPOINT = os.environ.get("QALL_MINIO_ENDPOINT", "http://127.0.0.1:9000")
MINIO_ACCESS_KEY = os.environ.get("QALL_MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("QALL_MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.environ.get("QALL_MINIO_BUCKET", "qall-dataloader-tests")

# dst used by every test: the bucket must appear at /bucket inside the container.
DL_DST = "bucket"
DL_NAME = "bucket"

WRITE_THEN_READ_SRC = """
from pathlib import Path


def write_then_read():
    target = Path("/bucket/dataloader-v2/hello.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("hello from dataloader v2")
    return target.read_text()
"""

READ_SEED_SRC = """
from pathlib import Path


def read_seed():
    return Path("/bucket/dataloader-v2/seed.txt").read_text()
"""


def _endpoint_reachable(endpoint: str, timeout: float = 1.0) -> bool:
    """Best-effort TCP probe so the suite skips instead of hanging on DNS/TCP."""
    parsed = urlparse(endpoint)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _minio_s3():
    """An s3fs filesystem pointed at the test MinIO, rooted at the test bucket."""
    import fsspec

    return fsspec.filesystem(
        "s3",
        key=MINIO_ACCESS_KEY,
        secret=MINIO_SECRET_KEY,
        client_kwargs={"endpoint_url": MINIO_ENDPOINT},
    )


def _require_minio() -> None:
    if not _endpoint_reachable(MINIO_ENDPOINT):
        pytest.skip(
            f"MinIO is not reachable at {MINIO_ENDPOINT}; skipping dataloader e2e"
        )
    try:
        fs = _minio_s3()
        if not fs.exists(MINIO_BUCKET):
            fs.mkdir(MINIO_BUCKET)
    except Exception as exc:  # pragma: no cover - depends on the environment
        pytest.skip(f"MinIO bucket {MINIO_BUCKET!r} is not usable: {exc}")


def _dataloader_entries(task_hash: str) -> list[dict]:
    return [
        {
            "task_hash": task_hash,
            "name": DL_NAME,
            "src": f"s3://{MINIO_BUCKET}",
            "dst": DL_DST,
            "credentials": {
                "key": MINIO_ACCESS_KEY,
                "secret": MINIO_SECRET_KEY,
                "endpoint_url": MINIO_ENDPOINT,
            },
        }
    ]


def _require_host_support() -> None:
    """Skip when the host cannot run rclone-backed volumes (fuse + plugin)."""
    from qall.daemon.dependencies import check_dataloader_dependencies

    report = check_dataloader_dependencies()
    if not report.ok:
        pytest.skip(
            "Host cannot mount remote dataloaders; run `qall dataloader setup`:\n"
            + report.summary()
        )


@pytest.mark.daemon
@pytest.mark.minio
def test_remote_dataloader_roundtrip(daemon_stack):
    """
    A remote dataloader is mounted at /<dst> and is read-write: the task writes
    a file through the kernel mount and the client observes it in the bucket.
    """
    _require_minio()
    _require_host_support()

    task_hash = daemon_stack.push_task(
        WRITE_THEN_READ_SRC, "write_then_read", entrypoint=True
    )
    output = daemon_stack.run(task_hash, dataloaders=_dataloader_entries(task_hash))

    assert output == "hello from dataloader v2"
    # The write went through the volume to the object storage (write-through VFS
    # cache), not just to a container-local directory.
    assert (
        _minio_s3().cat(f"{MINIO_BUCKET}/dataloader-v2/hello.txt")
        == b"hello from dataloader v2"
    )


@pytest.mark.daemon
@pytest.mark.minio
def test_remote_dataloader_sees_client_written_object(daemon_stack):
    """An object written by the client is visible through the task's mount."""
    _require_minio()
    _require_host_support()

    fs = _minio_s3()
    seed = f"seed-{uuid.uuid4().hex}.txt"
    with fs.open(f"{MINIO_BUCKET}/dataloader-v2/seed.txt", "wb") as f:
        f.write(seed.encode())

    task_hash = daemon_stack.push_task(READ_SEED_SRC, "read_seed", entrypoint=True)
    output = daemon_stack.run(task_hash, dataloaders=_dataloader_entries(task_hash))

    assert output == seed


@pytest.mark.daemon
@pytest.mark.minio
def test_dataloader_volumes_are_reaped_after_the_run(daemon_stack):
    """The per-(run, dataloader) volume does not outlive the run that used it."""
    _require_minio()
    _require_host_support()

    docker = pytest.importorskip("docker").from_env()

    task_hash = daemon_stack.push_task(READ_SEED_SRC, "read_seed", entrypoint=True)
    run_id = str(uuid.uuid4())
    daemon_stack.run(
        task_hash,
        workflow_run_id=run_id,
        dataloaders=_dataloader_entries(task_hash),
    )

    deadline = time.time() + 30
    while time.time() < deadline:
        leftover = docker.volumes.list(
            filters={"label": f"qall.workflow_run_id={run_id}"}
        )
        if not leftover:
            break
        time.sleep(1)

    assert not leftover, "dataloader volume(s) leaked after the run: " + ", ".join(
        v.name for v in leftover
    )


@pytest.mark.daemon
def test_dst_traversal_is_rejected_cleanly(daemon_stack):
    """
    An unsafe ``dst`` is refused by the daemon with a gRPC error — never a hang
    and never a raw Docker panic.
    """
    from grpc import RpcError

    from qall_daemon_client import GrpcDaemonClient
    from qall_daemon_client.v1.objects import DataloaderEntry

    task_hash = daemon_stack.push_task(READ_SEED_SRC, "read_seed", entrypoint=True)

    with GrpcDaemonClient(url=daemon_stack.address) as client:
        with pytest.raises(RpcError) as excinfo:
            client.create_task_run(
                task_hash=task_hash,
                workflow_run_id=str(uuid.uuid4()),
                dataloaders=[
                    DataloaderEntry(
                        task_hash=task_hash,
                        name="escape",
                        src=f"s3://{MINIO_BUCKET}",
                        dst="../../etc",
                        credentials={},
                    )
                ],
            )

    details = (excinfo.value.details() or "").lower()
    assert "panic" not in details
    assert details, "the daemon returned an empty error message"


@pytest.mark.daemon
def test_missing_rclone_plugin_yields_a_clean_error(daemon_stack):
    """
    On hosts where the plugin is *not* installed (e.g. CI), the daemon still
    answers promptly with FailedPrecondition and an actionable message instead
    of hanging on volume creation.
    """
    from grpc import RpcError, StatusCode

    from qall.daemon.dependencies import check_dataloader_dependencies
    from qall_daemon_client import GrpcDaemonClient
    from qall_daemon_client.v1.objects import DataloaderEntry

    if check_dataloader_dependencies().ok:
        pytest.skip(
            "rclone plugin + fuse are installed; the failure path is not reachable"
        )

    task_hash = daemon_stack.push_task(READ_SEED_SRC, "read_seed", entrypoint=True)

    with GrpcDaemonClient(url=daemon_stack.address) as client:
        with pytest.raises(RpcError) as excinfo:
            client.create_task_run(
                task_hash=task_hash,
                workflow_run_id=str(uuid.uuid4()),
                dataloaders=[
                    DataloaderEntry(
                        task_hash=task_hash,
                        name="unavailable",
                        src="s3://some-bucket",
                        dst="bucket",
                        credentials={"key": "x", "secret": "y"},
                    )
                ],
            )

    assert excinfo.value.code() == StatusCode.FAILED_PRECONDITION
    details = (excinfo.value.details() or "").lower()
    assert "panic" not in details
    assert "rclone" in details or "plugin" in details or "fuse" in details
