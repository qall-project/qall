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

from .utils import local_daemon_session, run_workflow_file  # noqa: F401

pytestmark = pytest.mark.daemon_integration


def test_qiskit_local_worker_end_to_end(tmp_path: Path, local_daemon_session):
    counts = run_workflow_file(
        tmp_path,
        "qiskit_bell_wf.py",
        """
        from qiskit import QuantumCircuit
        import qall

        @qall.workflow(requirements=["qiskit"])
        def main():
            qc = QuantumCircuit(2)
            qc.h(0)
            qc.cx(0, 1)
            qc.measure_all()
            result = qall.run(qc, shots=100)
            return dict(result.get_counts())
        """,
    )

    assert isinstance(counts, dict)
    assert sum(counts.values()) == 100
    assert set(counts.keys()).issubset({"00", "11"})
