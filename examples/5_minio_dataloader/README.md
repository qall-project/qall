# 6 — MinIO dataloader in a container

## Setup

1. Start a local object-storage stack **before** the qall daemon:

   Make sure to create a `qall-network` and attach it to the MinIO container.
   Run MinIO container (or its drop-in open replacement, pgsty/silo).

2. Define the dataloader. `src` points at the bucket prefix to bind, `dst` is
   the virtual mount point the task uses (`Path("local_minio")`). Credentials
   are **prompted for by default** (so they never leak into your shell
   history); flags are still supported for automation:

   ```sh
   # interactive (default): stores in the global config, prompts for
   # Access key / Secret key / optional Endpoint URL
   qall dataloader add local_minio s3://qall-dataloader-demo/local_minio local_minio \
     --endpoint_url=http://minio:9000 --use_ssl=false \
     --no-validate

   # non-interactive (automation): pass credentials as flags
   qall dataloader add local_minio s3://qall-dataloader-demo/local_minio local_minio \
     --key=minioadmin --secret=minioadmin \
     --endpoint_url=http://minio:9000 --use_ssl=false \
     --no-validate --no-prompt

   # store the dataloader in the current project's .qall.yml instead
   qall dataloader add local_minio s3://qall-dataloader-demo/local_minio local_minio \
     --current-project --key=minioadmin --secret=minioadmin \
     --endpoint_url=http://minio:9000 --use_ssl=false --no-validate
   ```

   Use the MinIO root credentials you configured.
   The bucket is created on first write (s3fs auto-creates it); you can also
   create it upfront with `mc mb qall-dataloader-demo` or the console.

3. Run the workflow locally (daemon path):

   ```sh
   qall run qall/examples/6_minio_dataloader/main.py --local
   ```

   The task downloads the image, writes it to
   MinIO, reads it back and asserts the round-trip is byte-identical.
