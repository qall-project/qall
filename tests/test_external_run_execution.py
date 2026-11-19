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

from pathlib import Path
import pytest

try:
    from .utils import (
        local_daemon_session,  # noqa: F401
        push_workflow_file,
        run_workflow_file,
    )
except ImportError:
    from tests.utils import (
        local_daemon_session,  # noqa: F401
        push_workflow_file,
        run_workflow_file,
    )

pytestmark = pytest.mark.daemon_integration


def test_exec_workflow_a_calls_task_by_hash(tmp_path: Path, local_daemon_session):
    task_hash = push_workflow_file(
        tmp_path,
        "target_task.py",
        """
        import qall

        @qall.workflow()
        def multiply_and_offset(x, factor, offset=0):
            return x * factor + offset
        """,
        tag_name="math_op",
    )

    result = run_workflow_file(
        tmp_path,
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
    )

    assert result == 45


def test_exec_workflow_a_calls_workflow_b(tmp_path: Path, local_daemon_session):
    push_workflow_file(
        tmp_path,
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

    result = run_workflow_file(
        tmp_path,
        "wf_a.py",
        """
        import qall

        @qall.workflow()
        def main():
            return qall.run("wf_b:v1", 5, y=4)
        """,
    )

    assert result == 60


def test_exec_transitive_workflow_a_calls_b_calls_c(
    tmp_path: Path, local_daemon_session
):
    push_workflow_file(
        tmp_path,
        "wf_c.py",
        """
        import qall

        @qall.workflow()
        def main(n):
            return n + 2
        """,
        tag_name="wf_c",
    )

    push_workflow_file(
        tmp_path,
        "wf_b.py",
        """
        import qall

        @qall.workflow()
        def main(n):
            return qall.run("wf_c:v1", n) * 5
        """,
        tag_name="wf_b",
    )

    result = run_workflow_file(
        tmp_path,
        "wf_a.py",
        """
        import qall

        @qall.workflow()
        def main(seed):
            return qall.run("wf_b:v1", seed) - 1
        """,
        3,
    )

    assert result == 24


def test_exec_diamond_workflow_a_calls_b_and_c_while_b_calls_c(
    tmp_path: Path, local_daemon_session
):
    push_workflow_file(
        tmp_path,
        "wf_c.py",
        """
        import qall

        @qall.workflow()
        def main(x):
            return x ** 2
        """,
        tag_name="wf_c",
    )

    push_workflow_file(
        tmp_path,
        "wf_b.py",
        """
        import qall

        @qall.workflow()
        def main(x):
            return qall.run("wf_c:v1", x) + 10
        """,
        tag_name="wf_b",
    )

    result = run_workflow_file(
        tmp_path,
        "wf_a.py",
        """
        import qall

        @qall.workflow()
        def main(x):
            res_b = qall.run("wf_b:v1", x)
            res_c = qall.run("wf_c:v1", x)
            return {"from_b": res_b, "from_c": res_c, "total": res_b + res_c}
        """,
        4,
    )

    assert result == {
        "from_b": 26,
        "from_c": 16,
        "total": 42,
    }
