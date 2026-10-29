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

from pathlib import Path
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
    dataloaders_file: Optional[str] = None,
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

        # Dataloaders are read by the subprocess from the conventioned secrets
        # file (/dev/shm/qall-dataloaders/<task_hash>.json), which the
        # executor (daemonless path) or the host client (daemon path) already
        # populated with *resolved* credentials. The wrapper only references the
        # file path, so plaintext credentials never appear in the wrapper code
        # or in env vars, and no host keyring is needed inside the container.
        dataloader_bootstrap_code = ""
        if dataloaders_file:
            dataloader_bootstrap_code = textwrap.dedent(f"""
                _dl_path = {dataloaders_file!r}
                if _dl_path and os.path.exists(_dl_path):
                    import json as _json
                    from qall.runtime.dataloader import bind_dataloaders as _bind
                    with open(_dl_path, encoding="utf-8") as _f:
                        _dl_map = _json.load(_f)
                    _dl_specs = [
                        {{
                            "name": _name,
                            "src": _spec["src"],
                            "dst": _spec["dst"],
                            "secrets": _spec.get("creds", {{}}),
                        }}
                        for _name, _spec in _dl_map.items()
                    ]
                    _bind(_dl_specs) #, sandbox_root=os.getcwd())
                    print("[Executor] Bound dataloader(s) to task filesystem.")
                """)

        wrapper_code = f"""
import asyncio
import cloudpickle
import os
import qall
import sys

{dataloader_bootstrap_code}
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
