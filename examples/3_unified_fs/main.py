import asyncio
from datetime import datetime
from pathlib import Path
import random
import time
import uuid

from qorus import task, workflow


def append_text(path: str, text: str) -> int:
    res = 0
    with path.open(mode="a") as f:
        res = f.write(text)
    return res


@task()
async def file_watchdog(dir: str, timeout: int):
    """
    Looks for a txt file on the given dir until it reaches 'timeout' seconds.
    """

    fs_map = set()
    log_file = dir / "file_watchdog.log"

    start = time.time()
    while time.time() - start < timeout:
        files = set(dir.glob("*"))

        deleted_files = fs_map.difference(files)
        created_files = files.difference(fs_map)

        for f in deleted_files:
            append_text(log_file, f"[{datetime.now()}] FILE DELETED -> {str(f)}\n")
        for f in created_files:
            append_text(log_file, f"[{datetime.now()}] FILE CREATED -> {str(f)}\n")

        fs_map = files
        time.sleep(1)


@task()
async def rand_fsio(dir: Path, timeout: int):

    created: list[str] = []

    start = time.time()
    rand_time = random.randint(0, 10)
    while time.time() - start < timeout:
        rand_time = random.randint(0, 9)
        time.sleep(rand_time)
        if len(created) and rand_time % 2:
            fdel = dir / created.pop(0)
            print(f"[{datetime.now()}] Deleting {fdel}")
            fdel.unlink()
        else:
            name = str(uuid.uuid4())[:8] + ".qoqo"
            fcrea = dir / name
            print(f"[{datetime.now()}] Creating {fcrea}")
            fcrea.touch()


@workflow()
async def main():
    BASE_DIR = Path(".")
    TIMEOUT = 180

    await asyncio.gather(
        asyncio.to_thread(file_watchdog, BASE_DIR, TIMEOUT),
        asyncio.to_thread(rand_fsio, BASE_DIR, TIMEOUT),
    )

    return 0
