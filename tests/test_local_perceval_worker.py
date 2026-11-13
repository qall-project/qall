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


def test_perceval_local_worker_end_to_end(tmp_path: Path, local_daemon_session):
    counts = run_workflow_file(
        tmp_path,
        "perceval_hom_wf.py",
        """
        import perceval as pcvl
        import qall

        @qall.workflow(requirements=["perceval-quandela"])
        def main():
            circuit = pcvl.Circuit(2) // pcvl.BS()
            result = qall.run(circuit, shots=100)
            raw = result["results"] if isinstance(result, dict) and "results" in result else result
            return {str(state): int(count) for state, count in raw.items()}
        """,
    )

    assert isinstance(counts, dict)
    assert sum(counts.values()) > 0
