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
import cloudpickle
import socket
import textwrap
import threading
import time
import pytest

from pathlib import Path

pytest.importorskip("perceval")

from qall.object import Tag
from qall.registry import BlockRegistry
from qall.runtime import (
    TaskRuntimeExecutor,
    WorkerRuntimeExecutor,
    LocalArtifactBackend,
)
from qall.specification import WorkflowSpec, WorkerSpec


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def test_perceval_local_worker_end_to_end(tmp_path: Path):
    registry = BlockRegistry(tmp_path / "registry")
    artifact_backend = LocalArtifactBackend(tmp_path / "artifacts")
    port = _get_free_port()

    worker_file = (
        Path(__file__).parents[1]
        / "qall"
        / "provider"
        / "qc"
        / "local"
        / "perceval_local_qc_worker.py"
    )
    worker_spec = WorkerSpec(worker_file)
    worker_dag = registry.create_worker_dag(worker_spec)
    registry.push(tag=Tag(name="perceval_worker", version="local"), dag=worker_dag)

    worker_executor = WorkerRuntimeExecutor(
        worker_hash=worker_dag.root_hash,
        registry=registry,
        port=port,
    )
    worker_thread = threading.Thread(target=worker_executor.execute, daemon=True)
    worker_thread.start()
    time.sleep(3)

    task_file = tmp_path / "task_perceval.py"
    task_file.write_text(
        textwrap.dedent(
            """
        import qall
        import perceval as pcvl

        @qall.task()
        def photonic_task():
            # Circuit optique linéaire simple
            circuit = pcvl.Circuit(2)
            circuit.add(0, pcvl.BS())
            
            # Définition de l'expérience photonique
            exp = pcvl.Experiment(circuit, pcvl.BasicState([1, 0]))
            
            res = qall.run(exp, shots=100)
            return len(res) > 0
    """
        )
    )

    task_spec = WorkflowSpec(task_file)
    task_dag = registry.create_workflow_dag(task_spec)
    registry.push(tag=Tag(name="perceval_task", version="v1"), dag=task_dag)

    task_executor = TaskRuntimeExecutor(
        task_hash=task_dag.root_hash,
        registry=registry,
        artifact_backend=artifact_backend,
        worker_addresses=[f"127.0.0.1:{port}"],
    )

    output = task_executor.execute(task_run_id="run_perceval_test")

    assert output.return_code == 0, f"Task execution failed: {output.stderr}"
    assert output.output_artifact_bytes is not None

    has_samples = cloudpickle.loads(output.output_artifact_bytes)
    assert has_samples is True
