import asyncio
from datetime import datetime
from pathlib import Path
import random
import time
import uuid

from qall import task, workflow


def append_text(path: Path, text: str) -> int:
    res = 0
    with path.open(mode="a") as f:
        res = f.write(text)
    return res


@task()
async def file_watchdog(dir: Path, timeout: int):
    """
    Looks for a txt file on the given dir until it reaches 'timeout' seconds.
    """

    fs_map = set()
    log_file = dir / "file_watchdog.log"

    start = time.time()

    print("Starting file_watchdog loop")

    while time.time() - start < timeout:
        files = set(dir.glob("*"))

        deleted_files = fs_map.difference(files)
        created_files = files.difference(fs_map)

        for f in deleted_files:
            append_text(log_file, f"[{datetime.now()}] FILE DELETED -> {str(f)}\n")
        for f in created_files:
            append_text(log_file, f"[{datetime.now()}] FILE CREATED -> {str(f)}\n")

        fs_map = files
        await asyncio.sleep(1)


@task()
async def rand_fsio(dir: Path, timeout: int):

    created: list[str] = []

    start = time.time()
    rand_time = random.randint(0, 10)

    print("Starting rand_fsio loop")

    while time.time() - start < timeout:
        rand_time = random.randint(0, 9)
        await asyncio.sleep(rand_time)
        if len(created) and rand_time % 2:
            fdel = dir / created.pop(0)
            print(f"[{datetime.now()}] Deleting {fdel}")
            fdel.unlink()
        else:
            name = str(uuid.uuid4())[:8] + ".qoqo"
            created.append(name)
            fcrea = dir / name
            print(f"[{datetime.now()}] Creating {fcrea}")
            fcrea.touch()


@workflow()
async def main():
    BASE_DIR = Path(".") / "unifs"
    TIMEOUT = 180

    print(f"Launching task group on {BASE_DIR.absolute()}")

    async with asyncio.TaskGroup() as tg:
        tg.create_task(file_watchdog(BASE_DIR, TIMEOUT))
        tg.create_task(rand_fsio(BASE_DIR, TIMEOUT))

    return 0
