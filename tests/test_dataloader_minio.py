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
MinIO integration tests.

Requires a MinIO instance reachable at http://localhost:9000 (see
infrastructure/local/docker-compose.yml, `make start`). Marked ``minio`` and
skipped automatically when the endpoint is unreachable.
"""

import cloudpickle
import os
import pytest
import shutil
import tempfile

from pathlib import Path

from qall.core import dataloader as core_dl
from qall.registry import BlockRegistry
from qall.registry.blockstore import LocalBlockstore
from qall.runtime import TaskRuntimeExecutor, LocalArtifactBackend
from qall.object import TaskEnvironment, TaskMetadata, TaskNode, TaskPayload
from qall.codec import DEFAULT_CODEC

MINIO_ENDPOINT = os.environ.get("QALL_MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET = os.environ.get("QALL_MINIO_BUCKET", "qall-dataloader-tests")

STORAGE_OPTIONS = {
    "key": MINIO_ACCESS_KEY,
    "secret": MINIO_SECRET_KEY,
    "endpoint_url": MINIO_ENDPOINT,
    "use_ssl": False,
    "client_kwargs": {"endpoint_url": MINIO_ENDPOINT},
}


def _minio_available() -> bool:
    try:
        import s3fs

        fs = s3fs.S3FileSystem(**STORAGE_OPTIONS)
        fs.ls("")
        return True
    except Exception:
        return False


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch):
    path = tmp_path / "qall-config.json"
    monkeypatch.setenv("QALL_CONFIG_PATH", str(path))
    return path


@pytest.fixture
def minio_blobs():
    if not _minio_available():
        pytest.skip("MinIO is not reachable at " + MINIO_ENDPOINT)

    import s3fs

    fs = s3fs.S3FileSystem(**STORAGE_OPTIONS)
    try:
        fs.mkdir(MINIO_BUCKET)
    except FileExistsError:
        pass
    fs.write_text(f"{MINIO_BUCKET}/mnist/table.csv", "x,y\n1,2\n3,4\n")
    fs.write_text(f"{MINIO_BUCKET}/mnist/notes.txt", "hello minio\n")

    yield fs

    fs.rm(MINIO_BUCKET, recursive=True)


@pytest.fixture
def minio_fs_blobs():
    """Seeds a richer object tree under the ``fs/`` prefix for filesystem-API tests."""
    if not _minio_available():
        pytest.skip("MinIO is not reachable at " + MINIO_ENDPOINT)

    import s3fs

    fs = s3fs.S3FileSystem(**STORAGE_OPTIONS)
    try:
        fs.mkdir(MINIO_BUCKET)
    except FileExistsError:
        pass
    try:
        fs.rm(f"{MINIO_BUCKET}/fs", recursive=True)
    except FileNotFoundError:
        pass
    fs.write_text(f"{MINIO_BUCKET}/fs/mnist/table.csv", "x,y\n1,2\n3,4\n")
    fs.write_text(f"{MINIO_BUCKET}/fs/mnist/notes.txt", "hello minio\n")
    fs.write_bytes(f"{MINIO_BUCKET}/fs/mnist/sub/deep.bin", b"\x00\x01\x02\xff")
    fs.write_bytes(f"{MINIO_BUCKET}/fs/pics/photo1.png", b"\x89PNG\r\n\x1a\n")
    fs.write_bytes(f"{MINIO_BUCKET}/fs/pics/album/photo2.jpg", b"jpgdata")

    yield fs

    fs.rm(MINIO_BUCKET, recursive=True)


@pytest.mark.minio
def test_task_reads_from_minio(config_path, minio_blobs):
    """A task reads blobs from MinIO through a bound s3:// dataloader."""
    core_dl.ensure_config()
    config = core_dl.load_config()
    # Plaintext creds are used directly here so the test is hermetic (no host
    # keyring dependency inside the task subprocess).
    config["dataloaders"]["mnist"] = {
        "src": f"s3://{MINIO_BUCKET}/",
        "dst": "mnist",
        "creds": STORAGE_OPTIONS,
    }
    core_dl.save_config(config)

    store, tmpdir = _new_blockstore()

    source_code = """
def process_minio(input):

    from pathlib import Path

    base_path = Path("dataloaders/mnist")

    ls_base_path = tuple((base_path / "mnist").glob("*"))
    print(ls_base_path)

    with open((base_path / "mnist" / "notes.txt")) as f:
        note = f.read().strip()

    csv = Path("dataloaders/mnist/mnist/table.csv").read_text().strip().splitlines()

    return {"note": note, "csv": csv, "names": sorted(x.name for x in Path("dataloaders/mnist/mnist").iterdir())}
"""
    task_hash = _push_task(store, source_code, "process_minio", ["mnist"])
    executor = TaskRuntimeExecutor(
        task_hash=task_hash,
        registry=BlockRegistry(tmpdir),
        artifact_backend=LocalArtifactBackend(
            Path(tempfile.mkdtemp(prefix="minio-art-")) / "a"
        ),
    )
    result = executor.execute(
        task_run_id="minio-run",
        input_artifact=cloudpickle.dumps({"args": (None,), "kwargs": {}}),
    )

    assert result.return_code == 0, result.stderr
    output = cloudpickle.loads(result.output_artifact_bytes)
    assert output["note"] == "hello minio"
    assert output["csv"] == ["x,y", "1,2", "3,4"]
    assert output["names"] == ["notes.txt", "table.csv"]

    shutil.rmtree(tmpdir, ignore_errors=True)


def _execute_minio_task(
    source_code: str,
    task_name: str = "process_fs",
    dl_name: str = "fs",
    src: str = f"s3://{MINIO_BUCKET}/fs",
    dst: str = "data",
):
    """Pushes a task bound to the MinIO dataloader and runs it in a subprocess."""
    core_dl.ensure_config()
    config = core_dl.load_config()
    config["dataloaders"][dl_name] = {
        "src": src,
        "dst": dst,
        "creds": STORAGE_OPTIONS,
    }
    core_dl.save_config(config)

    store, tmpdir = _new_blockstore()
    try:
        task_hash = _push_task(store, source_code, task_name, [dl_name])
        executor = TaskRuntimeExecutor(
            task_hash=task_hash,
            registry=BlockRegistry(tmpdir),
            artifact_backend=LocalArtifactBackend(
                Path(tempfile.mkdtemp(prefix="minio-art-")) / "a"
            ),
        )
        return executor.execute(
            task_run_id="minio-fs-run",
            input_artifact=cloudpickle.dumps({"args": (None,), "kwargs": {}}),
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.minio
def test_task_fs_inspection_minio(config_path, minio_fs_blobs):
    """A task inspects the MinIO mount: list, scandir, stat, path checks, glob."""
    source_code = """
def process_fs(input):
    import glob
    import os
    from pathlib import Path

    base = "dataloaders/data"

    ls_root = sorted(os.listdir(base))
    ls_mnist = sorted(os.listdir(base + "/mnist"))

    scandir = []
    with os.scandir(base + "/mnist") as it:
        for e in it:
            scandir.append((e.name, e.is_dir(), e.is_file(), e.stat().st_size))

    st = os.stat(base + "/mnist/table.csv")
    st_size = st.st_size
    st_mtime = st.st_mtime

    path_checks = {
        "exists": os.path.exists(base + "/mnist/table.csv"),
        "lexists": os.path.lexists(base + "/mnist/table.csv"),
        "isfile": os.path.isfile(base + "/mnist/table.csv"),
        "isdir": os.path.isdir(base + "/mnist"),
        "missing_exists": os.path.exists(base + "/nope"),
        "getsize": os.path.getsize(base + "/mnist/table.csv"),
        "getmtime": os.path.getmtime(base + "/mnist/table.csv"),
        "getatime": os.path.getatime(base + "/mnist/table.csv"),
        "getctime": os.path.getctime(base + "/mnist/table.csv"),
    }

    p_mnist = Path(base) / "mnist"
    pathlib_checks = {
        "is_dir": p_mnist.is_dir(),
        "is_file": p_mnist.is_file(),
        "exists": (p_mnist / "table.csv").exists(),
        "st_size": (p_mnist / "table.csv").stat().st_size,
        "st_mtime": (p_mnist / "table.csv").stat().st_mtime,
        "iterdir": sorted(x.name for x in p_mnist.iterdir()),
    }

    globbed = sorted(glob.glob(base + "/mnist/*.csv"))
    iglobbed = sorted(glob.iglob(base + "/mnist/*.csv"))
    recursive = sorted(glob.glob(base + "/**/*.csv", recursive=True))
    recursive_bin = sorted(glob.glob(base + "/**/*.bin", recursive=True))

    p_glob = sorted(x.name for x in p_mnist.glob("*.csv"))
    p_rglob = sorted(os.path.relpath(str(x)) for x in Path(base).rglob("*.csv"))

    return {
        "ls_root": ls_root,
        "ls_mnist": ls_mnist,
        "scandir": sorted(scandir),
        "st_size": st_size,
        "st_mtime": st_mtime,
        "path_checks": path_checks,
        "pathlib_checks": pathlib_checks,
        "globbed": globbed,
        "iglobbed": iglobbed,
        "recursive": recursive,
        "recursive_bin": recursive_bin,
        "p_glob": p_glob,
        "p_rglob": p_rglob,
    }
"""
    result = _execute_minio_task(source_code)
    assert result.return_code == 0, result.stderr
    output = cloudpickle.loads(result.output_artifact_bytes)

    assert output["ls_root"] == ["mnist", "pics"]
    assert output["ls_mnist"] == ["notes.txt", "sub", "table.csv"]

    scandir = {
        name: (is_dir, is_file, size)
        for name, is_dir, is_file, size in output["scandir"]
    }
    assert scandir["table.csv"] == (False, True, 12)
    assert scandir["notes.txt"] == (False, True, 12)
    assert scandir["sub"] == (True, False, 0)

    assert output["st_size"] == 12
    assert output["st_mtime"] > 0

    pc = output["path_checks"]
    assert pc["exists"] is True
    assert pc["lexists"] is True
    assert pc["isfile"] is True
    assert pc["isdir"] is True
    assert pc["missing_exists"] is False
    assert pc["getsize"] == 12
    assert pc["getmtime"] > 0
    assert pc["getatime"] > 0
    assert pc["getctime"] > 0

    pl = output["pathlib_checks"]
    assert pl["is_dir"] is True
    assert pl["is_file"] is False
    assert pl["exists"] is True
    assert pl["st_size"] == 12
    assert pl["st_mtime"] > 0
    assert pl["iterdir"] == ["notes.txt", "sub", "table.csv"]

    assert output["globbed"] == ["dataloaders/data/mnist/table.csv"]
    assert output["iglobbed"] == ["dataloaders/data/mnist/table.csv"]
    assert output["recursive"] == ["dataloaders/data/mnist/table.csv"]
    assert output["recursive_bin"] == ["dataloaders/data/mnist/sub/deep.bin"]
    assert output["p_glob"] == ["table.csv"]
    assert output["p_rglob"] == ["dataloaders/data/mnist/table.csv"]


@pytest.mark.minio
def test_task_fs_readwrite_minio(config_path, minio_fs_blobs):
    """A task writes to and reads from the MinIO mount (open, Path, touch, append)."""
    source_code = """
def process_fs(input):
    import os
    from pathlib import Path

    base = "dataloaders/data"

    # plain open write then read back
    with open(base + "/out.txt", "w") as f:
        f.write("first line\\n")
    with open(base + "/out.txt") as f:
        text_w = f.read()

    # append
    with open(base + "/out.txt", "a") as f:
        f.write("appended\\n")
    with open(base + "/out.txt") as f:
        text_append = f.read()

    # pathlib text
    Path(base + "/t2.txt").write_text("hello text\\n")
    text_t2 = Path(base + "/t2.txt").read_text()

    # pathlib bytes
    Path(base + "/raw.bin").write_bytes(b"\\x00\\x01\\x02\\xff\\xfe")
    raw = Path(base + "/raw.bin").read_bytes()

    # binary open
    with open(base + "/bin2.bin", "wb") as f:
        f.write(b"\\x89PNG\\r\\n\\x1a\\n")
    with open(base + "/bin2.bin", "rb") as f:
        bin2 = f.read()

    # touch -> empty file
    p = Path(base + "/empty.txt")
    p.touch()
    touched_size = os.path.getsize(base + "/empty.txt")
    touched_exists = p.exists()

    # overwrite (truncate) an existing seeded file
    with open(base + "/mnist/notes.txt", "w") as f:
        f.write("overwritten\\n")
    with open(base + "/mnist/notes.txt") as f:
        notes = f.read()

    # overwrite the empty file with content
    with open(base + "/empty.txt", "w") as f:
        f.write("now has content\\n")
    truncated_size = os.path.getsize(base + "/empty.txt")

    return {
        "text_w": text_w,
        "text_append": text_append,
        "text_t2": text_t2,
        "raw": raw,
        "bin2": bin2,
        "touched_size": touched_size,
        "touched_exists": touched_exists,
        "notes": notes,
        "truncated_size": truncated_size,
    }
"""
    result = _execute_minio_task(source_code)
    assert result.return_code == 0, result.stderr
    output = cloudpickle.loads(result.output_artifact_bytes)

    assert output["text_w"] == "first line\n"
    assert output["text_append"] == "first line\nappended\n"
    assert output["text_t2"] == "hello text\n"
    assert output["raw"] == b"\x00\x01\x02\xff\xfe"
    assert output["bin2"] == b"\x89PNG\r\n\x1a\n"
    assert output["touched_size"] == 0
    assert output["touched_exists"] is True
    assert output["notes"] == "overwritten\n"
    assert output["truncated_size"] == len("now has content\n")

    # Writes landed on MinIO (host-side verification).
    fs = minio_fs_blobs
    assert fs.read_text(f"{MINIO_BUCKET}/fs/out.txt") == "first line\nappended\n"
    assert fs.read_text(f"{MINIO_BUCKET}/fs/t2.txt") == "hello text\n"
    assert fs.read_bytes(f"{MINIO_BUCKET}/fs/raw.bin") == b"\x00\x01\x02\xff\xfe"
    assert fs.read_bytes(f"{MINIO_BUCKET}/fs/bin2.bin") == b"\x89PNG\r\n\x1a\n"
    assert fs.read_text(f"{MINIO_BUCKET}/fs/empty.txt") == "now has content\n"
    assert fs.read_text(f"{MINIO_BUCKET}/fs/mnist/notes.txt") == "overwritten\n"


@pytest.mark.minio
def test_task_fs_directory_ops_minio(config_path, minio_fs_blobs):
    """Directory APIs on the MinIO mount (mkdir/makedirs/rmdir semantics)."""
    source_code = """
def process_fs(input):
    import glob
    import os
    from pathlib import Path

    base = "dataloaders/data"

    # os.mkdir: S3 has no real dir objects, so materialize it with a child file.
    os.mkdir(base + "/created")
    with open(base + "/created/f.txt", "w") as f:
        f.write("hi\\n")
    mkdir_isdir = os.path.isdir(base + "/created")
    mkdir_list = sorted(os.listdir(base + "/created"))
    mkdir_glob = sorted(glob.glob(base + "/created/*.txt"))

    # Path.mkdir is idempotent with exist_ok.
    Path(base + "/created").mkdir(exist_ok=True)
    p_mkdir_ok = True

    # os.makedirs creates intermediate parents.
    os.makedirs(base + "/a/b/c", exist_ok=True)
    with open(base + "/a/b/c/deep.txt", "w") as f:
        f.write("deep\\n")
    makedirs_isdir = os.path.isdir(base + "/a/b/c")
    a_list = sorted(os.listdir(base + "/a"))
    b_list = sorted(os.listdir(base + "/a/b"))
    c_list = sorted(os.listdir(base + "/a/b/c"))

    # Path.mkdir(parents=True) is idempotent.
    Path(base + "/x/y").mkdir(parents=True, exist_ok=True)
    with open(base + "/x/y/leaf.txt", "w") as f:
        f.write("leaf\\n")
    x_isdir = os.path.isdir(base + "/x/y")

    # All files are in place: recursive glob sees every *.txt under the mount.
    nested_glob = sorted(glob.glob(base + "/**/*.txt", recursive=True))

    # rmdir: S3 has no real empty directories, so removing a now-empty prefix
    # raises FileNotFoundError rather than succeeding like POSIX.
    os.remove(base + "/created/f.txt")
    try:
        os.rmdir(base + "/created")
        rmdir_raised = False
    except FileNotFoundError:
        rmdir_raised = True

    return {
        "mkdir_isdir": mkdir_isdir,
        "mkdir_list": mkdir_list,
        "mkdir_glob": mkdir_glob,
        "p_mkdir_ok": p_mkdir_ok,
        "makedirs_isdir": makedirs_isdir,
        "nested_glob": nested_glob,
        "a_list": a_list,
        "b_list": b_list,
        "c_list": c_list,
        "x_isdir": x_isdir,
        "rmdir_raised": rmdir_raised,
    }
"""
    result = _execute_minio_task(source_code)
    assert result.return_code == 0, result.stderr
    output = cloudpickle.loads(result.output_artifact_bytes)

    assert output["mkdir_isdir"] is True
    assert output["mkdir_list"] == ["f.txt"]
    assert output["mkdir_glob"] == ["dataloaders/data/created/f.txt"]
    assert output["p_mkdir_ok"] is True
    assert output["makedirs_isdir"] is True
    assert output["nested_glob"] == [
        "dataloaders/data/a/b/c/deep.txt",
        "dataloaders/data/created/f.txt",
        "dataloaders/data/mnist/notes.txt",
        "dataloaders/data/x/y/leaf.txt",
    ]
    assert output["a_list"] == ["b"]
    assert output["b_list"] == ["c"]
    assert output["c_list"] == ["deep.txt"]
    assert output["x_isdir"] is True
    assert output["rmdir_raised"] is True


@pytest.mark.minio
def test_task_fs_delete_rename_minio(config_path, minio_fs_blobs):
    """Delete and rename APIs on the MinIO mount (remove/unlink/rename)."""
    source_code = """
def process_fs(input):
    import os
    from pathlib import Path

    base = "dataloaders/data"

    # seed files to delete
    with open(base + "/tmp.txt", "w") as f:
        f.write("to delete\\n")
    with open(base + "/tmp2.txt", "w") as f:
        f.write("to delete 2\\n")

    # os.remove
    os.remove(base + "/tmp.txt")
    removed_gone = not os.path.exists(base + "/tmp.txt")

    # os.unlink
    os.unlink(base + "/tmp2.txt")
    unlinked_gone = not os.path.exists(base + "/tmp2.txt")

    # Path.unlink(missing_ok=True) on a missing file must not raise
    Path(base + "/never.txt").unlink(missing_ok=True)
    unlink_missing_ok = True

    # os.rename
    os.rename(base + "/mnist/notes.txt", base + "/mnist/renamed.txt")
    renamed_exists = os.path.isfile(base + "/mnist/renamed.txt")
    renamed_old_gone = not os.path.exists(base + "/mnist/notes.txt")
    renamed_content = Path(base + "/mnist/renamed.txt").read_text()

    # Path.rename
    moved = Path(base + "/mnist/table.csv").rename(base + "/moved.csv")
    moved_exists = moved.exists()
    moved_content = moved.read_text()
    moved_old_gone = not os.path.exists(base + "/mnist/table.csv")

    return {
        "removed_gone": removed_gone,
        "unlinked_gone": unlinked_gone,
        "unlink_missing_ok": unlink_missing_ok,
        "renamed_exists": renamed_exists,
        "renamed_old_gone": renamed_old_gone,
        "renamed_content": renamed_content,
        "moved_exists": moved_exists,
        "moved_content": moved_content,
        "moved_old_gone": moved_old_gone,
    }
"""
    result = _execute_minio_task(source_code)
    assert result.return_code == 0, result.stderr
    output = cloudpickle.loads(result.output_artifact_bytes)

    assert output["removed_gone"] is True
    assert output["unlinked_gone"] is True
    assert output["unlink_missing_ok"] is True
    assert output["renamed_exists"] is True
    assert output["renamed_old_gone"] is True
    assert output["renamed_content"] == "hello minio\n"
    assert output["moved_exists"] is True
    assert output["moved_content"] == "x,y\n1,2\n3,4\n"
    assert output["moved_old_gone"] is True

    # Deletes/renames landed on MinIO (host-side verification).
    fs = minio_fs_blobs
    assert fs.read_text(f"{MINIO_BUCKET}/fs/mnist/renamed.txt") == "hello minio\n"
    assert fs.read_text(f"{MINIO_BUCKET}/fs/moved.csv") == "x,y\n1,2\n3,4\n"
    assert not fs.exists(f"{MINIO_BUCKET}/fs/mnist/notes.txt")
    assert not fs.exists(f"{MINIO_BUCKET}/fs/mnist/table.csv")


@pytest.mark.minio
def test_task_fs_path_traversal_minio(config_path, minio_fs_blobs):
    """A task escaping the MinIO mount via `..` must be refused at runtime."""
    source_code = """
def malicious_minio(input):
    with open("dataloaders/data/../../etc/passwd") as f:
        return f.read()
"""
    result = _execute_minio_task(source_code, task_name="malicious_minio")
    assert result.return_code != 0
    assert "traversal" in result.stderr.lower()


def _new_blockstore() -> tuple[LocalBlockstore, Path]:
    tmpdir = Path(tempfile.mkdtemp(prefix="minio-store-"))
    store = LocalBlockstore(tmpdir)
    return store, tmpdir


def _push_task(
    store: LocalBlockstore,
    source_code: str,
    task_name: str,
    dataloaders: list[str] | None = None,
) -> str:
    payload = TaskPayload(
        code=source_code,
        code_format="raw",
        environment=TaskEnvironment(image="python:3.13").to_dict(),
    )
    payload_block = payload.to_block(DEFAULT_CODEC)
    payload_hash = payload_block.hash
    store.put(payload_hash, payload_block.data)

    metadata = TaskMetadata(
        name=task_name, entrypoint=True, pure=True, dataloaders=dataloaders or []
    )
    node = TaskNode(
        payload_hash=payload_hash,
        children={},
        metadata=metadata.to_dict(),
    )
    node_block = node.to_block(DEFAULT_CODEC)
    store.put(node_block.hash, node_block.data)
    return node_block.hash
