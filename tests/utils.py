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

import textwrap
import pytest

from pathlib import Path
from typing import Any, Optional

from qall.core.artifact import deserialize_local_artifact, list_local_artifacts
from qall.core.daemon import get_daemon_status, start_daemon, stop_daemon, push_artifact
from qall.core.run import run
from qall.object import DaemonStatus, Tag, WorkflowRunStatus
from qall.registry import BlockRegistry
from qall.specification import WorkflowSpec


def _ensure_host_registry_writable() -> None:
    """Ensures host registry folders remain writable if the Docker daemon runs as root."""
    try:
        from docker import from_env

        container = from_env().containers.get("qalld")
        container.exec_run("chmod -R a+rwX /block-registry /artifact-registry")
    except Exception:
        pass


@pytest.fixture(scope="module")
def local_daemon_session(tmp_path_factory):
    """
    Ensures a local Qall daemon is running with the local SDK mounted (QALL_DEV_DIR)
    and an isolated 'local' configuration profile.
    """
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    cfg_dir = tmp_path_factory.mktemp("qall-local-worker-cfg")
    mp.setenv("QALL_CONFIG_PATH", str(cfg_dir / "qall-config.json"))

    repo_root = Path(__file__).resolve().parents[1]
    mp.setenv("QALL_DEV_DIR", str(repo_root))

    started_here = False
    if get_daemon_status().status != DaemonStatus.RUNNING:
        try:
            start_daemon(port=50053, backend="docker", follow_logs=False)
            started_here = True
        except Exception as exc:
            mp.undo()
            pytest.skip(f"Local Qall daemon unavailable: {exc}")

    _ensure_host_registry_writable()

    try:
        yield
    finally:
        _ensure_host_registry_writable()
        if started_here:
            stop_daemon(port=50053, backend="docker")
        mp.undo()


def push_workflow_file(
    tmp_path: Path,
    filename: str,
    source_code: str,
    tag_name: str,
    version: str = "v1",
) -> str:
    """
    Compiles a workflow file into a Merkle DAG, pushes it to the local BlockRegistry
    under `tag_name:version`, and returns its root task hash.
    """
    _ensure_host_registry_writable()

    wf_path = tmp_path / filename
    wf_path.write_text(textwrap.dedent(source_code), encoding="utf-8")

    spec = WorkflowSpec(wf_path)
    registry = BlockRegistry()
    dag = registry.create_workflow_dag(spec)
    registry.push(tag=Tag(name=tag_name, version=version), dag=dag)

    _ensure_host_registry_writable()
    return dag.root_hash


def run_workflow_file(
    tmp_path: Path,
    filename: str,
    source_code: str,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    Writes a workflow file, pushes optional `*args`/`**kwargs` via `push_artifact`,
    executes the workflow via `create_workflow_run(..., local_only=True)`, and returns
    the deserialized output artifact.
    """
    _ensure_host_registry_writable()
    excluded_hashes = {art.hash for art in list_local_artifacts()}

    wf_path = tmp_path / filename
    wf_path.write_text(textwrap.dedent(source_code), encoding="utf-8")

    input_artifact_hash: Optional[str] = None
    if args or kwargs:
        input_artifact_hash = push_artifact({"args": args, "kwargs": kwargs})
        excluded_hashes.add(input_artifact_hash)

    wf_run, artifacts = run(
        entrypoint_file=str(wf_path),
        workflow_name=wf_path.stem,
        local_only=True,
        run_input_artifact_hash=input_artifact_hash,
    )
    assert wf_run.status == WorkflowRunStatus.DONE, f"Workflow '{wf_path.stem}' failed"
    _ensure_host_registry_writable()

    if artifacts:
        last = artifacts[-1]
        return deserialize_local_artifact(last.hash)

    new_artifacts = [
        art for art in list_local_artifacts() if art.hash not in excluded_hashes
    ]
    assert new_artifacts, f"No output artifact produced by workflow '{wf_path.stem}'"

    return deserialize_local_artifact(new_artifacts[-1].hash)
