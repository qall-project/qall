# Copyright 2026 Scaleway
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import tempfile
import textwrap
from pathlib import Path

from qall.specification import WorkerSpec


def test_worker_spec_from_file_with_missing_third_party_imports():
    """
    Instantiating a WorkerSpec from a @quantum_worker file must not require
    third-party packages to be installed locally: missing imports are stubbed
    during compilation and auto-added to requirements.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "my_worker.py"
        filepath.write_text(textwrap.dedent("""
            import qall_test_missing_qiskit as qk
            from qall_test_missing_aer import AerSimulator

            from qall.provider.qc import (
                QuantumWorker,
                QuantumContext,
                quantum_worker,
            )

            @quantum_worker(
                input_format="qiskit",
                output_format="qiskit",
            )
            class MyWorker(QuantumWorker):
                def run(self, program, shots, context, **kwargs):
                    backend = AerSimulator()
                    return backend.run(program, shots=shots).result()
            """))

        spec = WorkerSpec(filepath)

        assert spec.name == "MyWorker"
        assert "qall_test_missing_qiskit" in spec.requirements
        assert "qall_test_missing_aer" in spec.requirements
        assert spec.source is not None

        # Stub modules must not leak into the process.
        assert "qall_test_missing_qiskit" not in sys.modules
        assert "qall_test_missing_aer" not in sys.modules


def test_worker_spec_without_third_party_imports():
    """Plain workers keep working with empty requirements."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "plain_worker.py"
        filepath.write_text(textwrap.dedent("""
            from qall.provider.qc import (
                QuantumWorker,
                QuantumContext,
                quantum_worker,
            )

            @quantum_worker(
                input_format="qiskit",
                output_format="qiskit",
            )
            class PlainWorker(QuantumWorker):
                def run(self, program, shots, context, **kwargs):
                    return program
            """))

        spec = WorkerSpec(filepath)

        assert spec.name == "PlainWorker"
        assert spec.requirements == []
        assert spec.source is not None


def test_worker_imported_global_not_serialized():
    """
    A worker-method global already re-provided by a shipped external import
    (e.g. `from math import exp`) must not be pickled into the worker payload:
    the import alone suffices. Mirrors the TaskSpec re-export guard.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "worker_import_global.py"
        filepath.write_text(textwrap.dedent("""
            from math import exp

            from qall.provider.qc import (
                QuantumWorker,
                QuantumContext,
                quantum_worker,
            )

            @quantum_worker(
                input_format="qiskit",
                output_format="qiskit",
            )
            class ExpWorker(QuantumWorker):
                def run(self, program, shots, context, **kwargs):
                    return exp(shots)
            """))

        spec = WorkerSpec(filepath)

        assert "from math import exp" in spec.imports["external_imports"]
        assert "exp" not in spec.local_dependencies

        code = "\n\n".join(
            spec.imports["external_imports"]
            + list(spec.local_dependencies.values())
            + [spec.source]
        )
        assert "cloudpickle.loads" not in code
        assert "from math import exp" in code
