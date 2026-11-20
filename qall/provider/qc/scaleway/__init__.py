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
import qall.core as core

from pathlib import Path
from enum import StrEnum

from qall.specification import WorkerSpec

from ..catalog import WorkerCatalog, WorkerEntry


class ScalewayWorkerType(StrEnum):
    CIRQ = "cirq_scaleway_qc_worker"
    QISKIT = "qiskit_scaleway_qc_worker"
    CUDAQ = "cudaq_scaleway_qc_worker"
    PULSER = "pulser_scaleway_qc_worker"
    PERCEVAL = "perceval_scaleway_qc_worker"


def get_scaleway_worker_catalog() -> WorkerCatalog:
    catalog = WorkerCatalog()
    local_entries = {}

    base_dir = Path(__file__).parent.resolve()

    for worker in ScalewayWorkerType:
        file_path = base_dir / f"{worker.value}.py"

        if not file_path.exists():
            raise FileNotFoundError(f"Scaleway worker file not found: {file_path}")

        worker_spec = WorkerSpec(file_path)

        tag, dag = core.push_worker_on_registry(
            worker_spec=worker_spec,
            worker_name=file_path.stem,
            worker_version="latest",
            local_only=True,
        )

        local_entries[tag.name] = WorkerEntry(
            hash=dag.root_hash,
            version=tag.version,
            provider="scaleway",
            input_format=worker_spec.input_format,
        )

    return catalog
