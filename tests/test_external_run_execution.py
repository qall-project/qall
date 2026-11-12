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
from pathlib import Path
import cloudpickle
import pytest

from qall.config import get_default_configuration
from qall.core.daemon import apply_resource_assignments, run_task
from qall.daemon.docker_manager import DockerDaemonManager
from qall.object import Tag
from qall.registry import BlockRegistry
from qall.registry.local_artifact_registry import LocalArtifactRegistry
from qall.resolver import resolve_workflow_resources
from qall.specification import WorkflowSpec

pytestmark = pytest.mark.daemon_integration


@pytest.fixture
def daemon_env(tmp_path: Path, monkeypatch):
    """Starts a real Docker daemon wired to isolated block/artifact stores and local SDK sources."""
    registry_dir = tmp_path / "block-registry"
    artifacts_dir = tmp_path / "artifact-registry"
    registry_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)

    # Mount local qall sources so task containers use the modified SDK instead of PyPI
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("QALL_DEV_DIR", str(repo_root))

    manager = DockerDaemonManager(
        grpc_port=50053,
        http_port=8080,
        host_block_registry_path=str(registry_dir),
        host_artifact_registry_path=str(artifacts_dir),
    )

    with manager:
        registry = BlockRegistry(registry_dir)
        yield tmp_path, registry, manager, registry_dir, artifacts_dir


def _push_and_assign(
    daemon_env,
    filename: str,
    code: str,
    tag_name: str,
    version: str = "v1",
) -> str:
    """Compiles a workflow, pushes it to the registry, and registers resource assignments in the daemon."""
    tmp_path, registry, _, _, _ = daemon_env
    wf_file = tmp_path / filename
    wf_file.write_text(textwrap.dedent(code), encoding="utf-8")

    spec = WorkflowSpec(wf_file)
    dag = registry.create_workflow_dag(spec)
    registry.push(tag=Tag(name=tag_name, version=version), dag=dag)

    profile = get_default_configuration("local").get_default_profile()
    assignments = resolve_workflow_resources(
        task_dag=dag,
        profile=profile,
        available_resources=[],
        replace_to_local=True,
    )
    apply_resource_assignments(resource_assignments=assignments)
    return dag.root_hash


def _run_root(daemon_env, root_hash: str, *args, **kwargs):
    """Triggers execution via the daemon and deserializes the final output artifact."""
    _, _, manager, registry_dir, artifacts_dir = daemon_env

    input_hash = None
    if args or kwargs:
        payload = cloudpickle.dumps({"args": args, "kwargs": kwargs})
        with manager.client as client:
            input_hash = client.create_artifact("init", payload).hash

    artifacts = run_task(
        task_hash=root_hash,
        input_artifact_hash=input_hash,
        block_registry=str(registry_dir),
        artifact_registry=str(artifacts_dir),
    )
    assert artifacts, "Expected at least one output artifact"
    raw_bytes = LocalArtifactRegistry(artifacts_dir).read_bytes(artifacts[-1].hash)
    return cloudpickle.loads(raw_bytes)


def test_exec_workflow_a_calls_task_by_hash(daemon_env):
    task_hash = _push_and_assign(
        daemon_env,
        "target_task.py",
        """
        import qall

        @qall.workflow()
        def multiply_and_offset(x, factor, offset=0):
            return x * factor + offset
        """,
        tag_name="math_op",
    )

    root_a = _push_and_assign(
        daemon_env,
        "wf_a_hash.py",
        f"""
        import qall

        @qall.task()
        def produce():
            return 6

        @qall.workflow()
        def main():
            val = produce()
            return qall.run("{task_hash}", val, 7, offset=3)
        """,
        tag_name="wf_a_hash",
    )

    assert _run_root(daemon_env, root_a) == 45


def test_exec_workflow_a_calls_workflow_b(daemon_env):
    _push_and_assign(
        daemon_env,
        "wf_b.py",
        """
        import qall

        @qall.task()
        def sub_step(v):
            return v + 10

        @qall.workflow()
        def main(x, y=1):
            return sub_step(x) * y
        """,
        tag_name="wf_b",
    )

    root_a = _push_and_assign(
        daemon_env,
        "wf_a.py",
        """
        import qall

        @qall.workflow()
        def main():
            return qall.run("wf_b:v1", 5, y=4)
        """,
        tag_name="wf_a",
    )

    assert _run_root(daemon_env, root_a) == 60


def test_exec_transitive_workflow_a_calls_b_calls_c(daemon_env):
    _push_and_assign(
        daemon_env,
        "wf_c.py",
        """
        import qall

        @qall.workflow()
        def main(n):
            return n + 2
        """,
        tag_name="wf_c",
    )

    _push_and_assign(
        daemon_env,
        "wf_b.py",
        """
        import qall

        @qall.workflow()
        def main(n):
            return qall.run("wf_c:v1", n) * 5
        """,
        tag_name="wf_b",
    )

    root_a = _push_and_assign(
        daemon_env,
        "wf_a.py",
        """
        import qall

        @qall.workflow()
        def main(seed):
            return qall.run("wf_b:v1", seed) - 1
        """,
        tag_name="wf_a",
    )

    assert _run_root(daemon_env, root_a, 3) == 24


def test_exec_diamond_workflow_a_calls_b_and_c_while_b_calls_c(daemon_env):
    _push_and_assign(
        daemon_env,
        "wf_c.py",
        """
        import qall

        @qall.workflow()
        def main(x):
            return x ** 2
        """,
        tag_name="wf_c",
    )

    _push_and_assign(
        daemon_env,
        "wf_b.py",
        """
        import qall

        @qall.workflow()
        def main(x):
            return qall.run("wf_c:v1", x) + 10
        """,
        tag_name="wf_b",
    )

    root_a = _push_and_assign(
        daemon_env,
        "wf_a.py",
        """
        import qall

        @qall.workflow()
        def main(x):
            res_b = qall.run("wf_b:v1", x)
            res_c = qall.run("wf_c:v1", x)
            return {"from_b": res_b, "from_c": res_c, "total": res_b + res_c}
        """,
        tag_name="wf_a",
    )

    assert _run_root(daemon_env, root_a, 4) == {"from_b": 26, "from_c": 16, "total": 42}