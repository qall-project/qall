# Copyright 2026 Scaleway
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Run a task entrypoint in a dedicated subprocess.

The subprocess only receives the task source (plus worker bootstrap code); it
runs as-is inside the task container. Dataloaders need no in-process bootstrap:
the daemon creates an rclone-backed Docker volume per
``(workflow_run_id, dataloader_name)`` and mounts it at ``/<dst>`` in the task
container, so ``Path("/<dst>")`` is served by the kernel.
"""

from pathlib import Path
import os
import subprocess
import sys
import textwrap
import threading

from tempfile import TemporaryDirectory
from typing import Optional

from qall.config.paths import TASK_RUNTIME_WORKDIR
from qall.runtime.unifs import setup_unifs


def run_task_in_subprocess(
    source_code: str,
    entrypoint_name: str,
    input_artifact: Optional[bytes] = None,
    worker_addresses: Optional[list[str]] = None,
    interpreter: Optional[str] = None,
) -> dict:

    with TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "task_output.bin"

        if not interpreter:
            interpreter = sys.executable

        if worker_addresses:
            print("[Executor] Add quantum worker manager link...")

            init_workers_code = textwrap.dedent(f"""
                from qall.core import create_quantum_worker_manager, stop_quantum_worker_manager
                create_quantum_worker_manager({worker_addresses!r})
                """)

            stop_workers_code = textwrap.dedent(f"""
                stop_quantum_worker_manager()
                """)
        else:
            init_workers_code = ""
            stop_workers_code = "pass"

        wrapper_code = f"""
import asyncio
import cloudpickle
import os
import qall
import sys

{source_code}

{init_workers_code}

_args = ()
_kwargs = {{}}

try:
    input_data = cloudpickle.loads(sys.stdin.buffer.read())

    if isinstance(input_data, dict):
        # Extract explicit args and kwargs (removing them from input_data)
        _args = input_data.pop("args", ())
        _kwargs = input_data.pop("kwargs", {{}})
        
        # Ensure _kwargs is actually a dict in case of malformed input
        if not isinstance(_kwargs, dict):
            _kwargs = {{}}
            
        # Any remaining keys in input_data are added to _kwargs
        _kwargs.update(input_data)

except Exception as e:
    if not isinstance(e, EOFError):
        import sys
        print(f"Failed to deserialize input: {{e}}", file=sys.stderr)
        raise

result = {entrypoint_name}(*_args, **_kwargs)
if asyncio.iscoroutine(result):
    result = asyncio.run(result)

with open('{output_path}', 'wb') as f:
    cloudpickle.dump(result, f)

{stop_workers_code}
"""
        # Task execution only happens inside a qall task container, where the
        # daemon mounts the shared per-workflow-run filesystem at /workdir. A
        # host process cannot provide /workdir, so refuse loudly instead of
        # letting setup_unifs() fail with a cryptic PermissionError.
        try:
            workdir_ok = TASK_RUNTIME_WORKDIR.is_dir() and os.access(
                TASK_RUNTIME_WORKDIR, os.W_OK
            )
        except OSError:
            workdir_ok = False
        if not workdir_ok:
            raise RuntimeError(
                "Task execution requires the shared filesystem at "
                f"{TASK_RUNTIME_WORKDIR}, which only exists inside a qall task "
                "container. Run the task through the daemon (e.g. `qall "
                "workflow run` / `qall daemon run`); direct host execution is "
                "not supported."
            )

        setup_unifs()

        process = subprocess.Popen(
            [interpreter, "-c", wrapper_code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(TASK_RUNTIME_WORKDIR),
        )

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def _read_stream(stream, tag: str, lines: list[str]) -> None:
            for raw_line in iter(stream.readline, b""):
                line = raw_line.decode(errors="replace")
                lines.append(line)
                print(f"[SubProcess] {tag}: {line}", end="")

        stdout_thread = threading.Thread(
            target=_read_stream,
            args=(process.stdout, "STDOUT", stdout_lines),
        )
        stderr_thread = threading.Thread(
            target=_read_stream,
            args=(process.stderr, "STDERR", stderr_lines),
        )
        stdout_thread.start()
        stderr_thread.start()

        if input_artifact:
            process.stdin.write(input_artifact)
            process.stdin.flush()
        process.stdin.close()

        return_code = process.wait()
        stdout_thread.join()
        stderr_thread.join()

        return_value = None
        if return_code == 0 and output_path.exists():
            return_value = output_path.read_bytes()

    return {
        "stdout": "".join(stdout_lines),
        "stderr": "".join(stderr_lines),
        "return_code": return_code,
        "return_value": return_value,
    }
