"""
Seeds the MinIO bucket used by the dataloader example and the MinIO tests.

Requires a MinIO instance at http://localhost:9000
(infrastructure/local/docker-compose.yml, `make start`).

Usage:
    python seed_minio.py
"""

import os

import s3fs

MINIO_ENDPOINT = os.environ.get("QALL_MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET = os.environ.get("QALL_MINIO_BUCKET", "qall-dataloader-demo")

STORAGE_OPTIONS = {
    "key": MINIO_ACCESS_KEY,
    "secret": MINIO_SECRET_KEY,
    "endpoint_url": MINIO_ENDPOINT,
    "use_ssl": False,
    "client_kwargs": {"endpoint_url": MINIO_ENDPOINT},
}


def main():
    fs = s3fs.S3FileSystem(**STORAGE_OPTIONS)
    try:
        fs.mkdir(MINIO_BUCKET)
        print(f"Created bucket {MINIO_BUCKET!r}")
    except FileExistsError:
        print(f"Bucket {MINIO_BUCKET!r} already exists")

    fs.write_text(f"{MINIO_BUCKET}/mnist/table.csv", "x,y\n1,2\n3,4\n5,6\n")
    fs.write_text(f"{MINIO_BUCKET}/mnist/notes.txt", "hello minio\n")
    fs.write_bytes(
        f"{MINIO_BUCKET}/pics/september/japan/fuji.png", b"\x89PNG\r\n\x1a\n"
    )

    print(f"Seeded MinIO dataloader storage at {MINIO_ENDPOINT}/{MINIO_BUCKET}")


if __name__ == "__main__":
    main()
