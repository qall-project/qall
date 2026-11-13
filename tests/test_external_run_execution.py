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

from qall.core.artifact import read_local_artifact_bytes
from qall.core.daemon import (
    run_task,
    start_daemon,
    stop_daemon,
)
from qall.daemon.docker_manager import _DEFAULT_IMAGE
from qall.object import Tag
from qall.registry import BlockRegistry
from qall.specification import WorkflowSpec

pytestmark = pytest.mark.daemon_integration


def _sweep_root_owned(target_dir: Path) -> None:
    """Removes root-owned files left by the Docker daemon container in target_dir."""
    try:
        from docker import from_env

        from_env().containers.run(
            image=_DEFAULT_IMAGE,
            entrypoint=["/bin/sh", "-c", f"rm -rf '/clean/{target_dir.name}'"],
            volumes={str(target_dir.parent): {"bind": "/clean", "mode": "rw"}},
            remove=True,
        )
    except Exception:
        pass


@pytest.fixture(scope="module")
def daemon_exec_env(tmp_path_factory):
    """Starts the local daemon once for the module with shared block/artifact registries."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    base_dir = tmp_path_factory.mktemp("qall-external-runs")
    block_dir = base_dir / "block-registry"
    artifact_dir = base_dir / "artifact-registry"
    block_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)

    registry = BlockRegistry(block_dir)

    # Mount local SDK sources so task containers use the modified qall codebase
    repo_root = Path(__file__).resolve().parents[1]
    mp.setenv("QALL_DEV_DIR", str(repo_root))

    try:
        start_daemon(
            port=50053,
            block_registry_path=block_dir,
            artifact_registry_path=artifact_dir,
            backend="docker",
            follow_logs=False,
        )
    except Exception as exc:
        mp.undo()
        pytest.skip(f"Daemon unavailable: {exc}")

    try:
        yield base_dir, registry, block_dir, artifact_dir
    finally:
        stop_daemon(port=50053, backend="docker")
        _sweep_root_owned(base_dir)
        mp.undo()


def _push_workflow(
    daemon_exec_env,
    filename: str,
    code: str,
    tag_name: str,
    version: str = "v1",
) -> str:
    base_dir, registry, _, _ = daemon_exec_env
    wf_file = base_dir / filename
    wf_file.write_text(textwrap.dedent(code), encoding="utf-8")

    spec = WorkflowSpec(wf_file)
    dag = registry.create_workflow_dag(spec)
    registry.push(tag=Tag(name=tag_name, version=version), dag=dag)

    # profile = get_default_configuration("local").get_default_profile()
    # assignments = resolve_workflow_resources(
    #     task_dag=dag,
    #     profile=profile,
    #     available_resources=[],
    #     replace_to_local=True,
    # )
    # apply_resource_assignments(resource_assignments=assignments)

    return dag.root_hash


def _run(daemon_exec_env, task_hash: str, *args, **kwargs):
    _, _, block_dir, artifact_dir = daemon_exec_env
    input_data = {"args": args, "kwargs": kwargs} if (args or kwargs) else None

    artifacts = run_task(
        task_hash=task_hash,
        input_artifact=input_data,
        block_registry=str(block_dir),
        artifact_registry=str(artifact_dir),
    )

    assert artifacts
    assert len(artifacts) >= 1

    final_artifact_bytes = read_local_artifact_bytes(
        artifacts[-1].hash,
        artifact_registry=str(artifact_dir),
    )
    return cloudpickle.loads(final_artifact_bytes)


def test_exec_workflow_a_calls_task_by_hash(daemon_exec_env):
    task_hash = _push_workflow(
        daemon_exec_env,
        "target_task.py",
        """
        import qall

        @qall.workflow()
        def multiply_and_offset(x, factor, offset=0):
            return x * factor + offset
        """,
        tag_name="math_op",
    )

    root_a = _push_workflow(
        daemon_exec_env,
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

    assert _run(daemon_exec_env, root_a) == 45


def test_exec_workflow_a_calls_workflow_b(daemon_exec_env):
    _push_workflow(
        daemon_exec_env,
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

    root_a = _push_workflow(
        daemon_exec_env,
        "wf_a.py",
        """
        import qall

        @qall.workflow()
        def main():
            return qall.run("wf_b:v1", 5, y=4)
        """,
        tag_name="wf_a",
    )

    assert _run(daemon_exec_env, root_a) == 60


def test_exec_transitive_workflow_a_calls_b_calls_c(daemon_exec_env):
    _push_workflow(
        daemon_exec_env,
        "wf_c.py",
        """
        import qall

        @qall.workflow()
        def main(n):
            return n + 2
        """,
        tag_name="wf_c",
    )

    _push_workflow(
        daemon_exec_env,
        "wf_b.py",
        """
        import qall

        @qall.workflow()
        def main(n):
            return qall.run("wf_c:v1", n) * 5
        """,
        tag_name="wf_b",
    )

    root_a = _push_workflow(
        daemon_exec_env,
        "wf_a.py",
        """
        import qall

        @qall.workflow()
        def main(seed):
            return qall.run("wf_b:v1", seed) - 1
        """,
        tag_name="wf_a",
    )

    assert _run(daemon_exec_env, root_a, 3) == 24


def test_exec_diamond_workflow_a_calls_b_and_c_while_b_calls_c(daemon_exec_env):
    _push_workflow(
        daemon_exec_env,
        "wf_c.py",
        """
        import qall

        @qall.workflow()
        def main(x):
            return x ** 2
        """,
        tag_name="wf_c",
    )

    _push_workflow(
        daemon_exec_env,
        "wf_b.py",
        """
        import qall

        @qall.workflow()
        def main(x):
            return qall.run("wf_c:v1", x) + 10
        """,
        tag_name="wf_b",
    )

    root_a = _push_workflow(
        daemon_exec_env,
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

    assert _run(daemon_exec_env, root_a, 4) == {
        "from_b": 26,
        "from_c": 16,
        "total": 42,
    }
