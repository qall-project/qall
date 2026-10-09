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
import subprocess
import sys
import textwrap
import threading

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from qall.runtime.unifs import UNIFIED_FS, setup_unifs


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

        init_workers_code = ""

        if worker_addresses:
            print("[Executor] Add quantum worker manager link...")
            init_workers_code = textwrap.dedent(
                f"""
                from qall.core import create_quantum_worker_manager
                create_quantum_worker_manager({worker_addresses!r})
                """
            )

        wrapper_code = f"""
import asyncio
import cloudpickle
import qall
import sys

{source_code}

{init_workers_code}

try:
    _args = ()
    _kwargs = {{}}

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
"""

        setup_unifs()

        process = subprocess.Popen(
            [interpreter, "-c", wrapper_code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(UNIFIED_FS),
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
