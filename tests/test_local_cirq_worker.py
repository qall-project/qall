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
import pytest

from pathlib import Path

from .utils import run_workflow_file, local_daemon_session

pytestmark = pytest.mark.daemon_integration


def test_cirq_local_worker_end_to_end(tmp_path: Path, local_daemon_session):
    counts = run_workflow_file(
        tmp_path,
        "cirq_bell_wf.py",
        """
        import cirq
        import qall

        @qall.workflow(requirements=["cirq-core"])
        def main():
            q0, q1 = cirq.LineQubit.range(2)
            circuit = cirq.Circuit(
                cirq.H(q0),
                cirq.CNOT(q0, q1),
                cirq.measure(q0, q1, key="m"),
            )
            result = qall.run(circuit, shots=100)
            return {int(k): int(v) for k, v in result.histogram(key="m").items()}
        """,
    )

    assert isinstance(counts, dict)
    assert sum(counts.values()) == 100
    assert set(counts.keys()).issubset({0, 3})
