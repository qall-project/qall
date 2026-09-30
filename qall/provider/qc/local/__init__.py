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

from qall.specification import WorkerSpec

from ..catalog import WorkerCatalog, WorkerEntry

__FILES = [
    "cirq_local_qc_worker.py",
    "qiskit_local_qc_worker.py",
]


def register_local_workers(catalog: WorkerCatalog = None) -> WorkerCatalog:
    catalog = catalog if catalog else WorkerCatalog()
    local_entries = {}

    base_dir = Path(__file__).parent.resolve()

    for file_name in __FILES:
        file_path = base_dir / file_name

        if not file_path.exists():
            raise FileNotFoundError(f"Local worker file not found: {file_path}")

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
            provider="local",
            input_formats=[worker_spec.input_format],
        )

    catalog.batch_add_and_save(local_entries)

    return catalog
