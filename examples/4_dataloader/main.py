"""
Dataloader example: bind an object storage as a virtual POSIX mount point and
process its data with plain stdlib I/O (open / Path / glob / os) + pandas.

It uses two dataloaders (see `qall dataloader add`):
  * "mnist"           -> mounted at ./mnist_dataset/  (src: file://<seed>/mnist)
  * "my_holiday_pics" -> mounted at pics              (src: file://<seed>/pics)

Setup:
  1. Start the local stack (optional, for the MinIO example):
        make start                                # infrastructure/local (registry + MinIO)
     then seed MinIO with:
        python qall/examples/4_dataloader/seed_minio.py
  2. Seed the local file:// sources:
        python qall/examples/4_dataloader/seed_local_storage.py
  3. Define the dataloaders through the CLI:
        qall dataloader add mnist file:///tmp/qall-dataloader-demo/mnist ./mnist_dataset/
        qall dataloader add my_holiday_pics file:///tmp/qall-dataloader-demo/pics pics
        qall dataloader add mnist_minio s3://qall-dataloader-demo/mnist ./mnist_minio/ \
          --key=minioadmin --secret=minioadmin --endpoint_url=http://localhost:9000 \
          --use_ssl=false
  4. Install an extra dep used by the workflow (auto-discovered and merged into
     the task image requirements, but needed locally for direct execution):
        uv pip install pandas
  5. Run it locally (daemon + container path, needs a running local daemon or
     pass --auto-start... see `qall run --help`):
        qall run qall/examples/4_dataloader/main.py --local

The client resolves the dataloader credentials from the host keyring and
provisions them at /dev/shm/qall-dataloaders/<task_hash>.json, which
the daemon bind-mounts read-only into each task container. The task then reads
/writes the object storage transparently through plain stdlib I/O.
"""

import asyncio
import glob
import os

from pathlib import Path

import pandas

from qall import task, workflow


@task(dataloaders=["mnist", "my_holiday_pics"], requirements=["pandas"])
async def remote_data_processing() -> dict:
    # Plain `open`: reads the object storage transparently.
    with open("mnist_dataset/table.csv") as f:
        header = f.readline().strip()

    # pandas.read_csv: relies on open()/Path under the hood, still transparent.
    df = pandas.read_csv("./mnist_dataset/table.csv")

    # pathlib.Path writes land back on the object storage.
    summary = Path("mnist_dataset/processed.txt")
    summary.write_text(f"rows={len(df)} header={header}\n")

    # os.listdir + glob see the virtual mount like any local directory.
    entries = sorted(os.listdir("mnist_dataset"))
    photos = sorted(glob.glob("pics/**/*.png", recursive=True))

    # Open a file for writing inside another mount point.
    with open("pics/september/japan/fuji.png", "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")

    return {
        "header": header,
        "mean_x": float(df["x"].mean()),
        "entries": entries,
        "photos": photos,
        "processed": summary.read_text().strip(),
    }


@workflow()
async def main():
    return await remote_data_processing()


if __name__ == "__main__":
    print(asyncio.run(main()))
