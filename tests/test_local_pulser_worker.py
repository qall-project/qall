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


def test_pulser_local_worker_end_to_end(tmp_path: Path, local_daemon_session):
    counts = run_workflow_file(
        tmp_path,
        "pulser_analog_wf.py",
        """
        import numpy as np
        import pulser
        import qall

        @qall.workflow(requirements=["pulser-core"])
        def main():
            reg = pulser.Register.square(2, spacing=5.0, prefix="q")
            seq = pulser.Sequence(reg, pulser.DigitalAnalogDevice)
            seq.declare_channel("rydberg", "rydberg_global")
            seq.add(pulser.Pulse.ConstantPulse(1000, np.pi, 0.0, 0.0), "rydberg")
            result = qall.run(seq, shots=100)
            return {str(k): int(v) for k, v in dict(result).items()}
        """,
    )

    assert isinstance(counts, dict)
    assert sum(counts.values()) == 100
