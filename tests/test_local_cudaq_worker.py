# Copyright 2026 Scaleway
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     [https://www.apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0)
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from pathlib import Path
import pytest

from .utils import local_daemon_session, run_workflow_file

pytestmark = pytest.mark.daemon_integration


def test_cudaq_local_worker_end_to_end(tmp_path: Path, local_daemon_session):
    counts = run_workflow_file(
        tmp_path,
        "cudaq_bell_wf.py",
        """
        import cudaq
        import qall

        @cudaq.kernel
        def bell():
            q = cudaq.qvector(2)
            h(q[0])
            x.ctrl(q[0], q[1])
            mz(q)

        @qall.workflow(requirements=["cudaq"])
        def main():
            result = qall.run(bell, shots=100)
            return {str(k): int(v) for k, v in result.items()}
        """,
    )

    assert isinstance(counts, dict)
    assert sum(counts.values()) == 100
    assert set(counts.keys()).issubset({"00", "11"})
