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
from typing import Optional, Union

from qall.object import ExecutionMode

from qall.core import (
    push_artifact,
    build_workflow,
    plan_workflow,
    create_workflow_run,
    get_workflow_from_hash,
)


def run(
    entrypoint_file: Optional[str] = None,
    entrypoint_hash: Optional[str] = None,
    execution_mode: Union[ExecutionMode, str] = "remote",
    allowed_qpus: Optional[list[str]] = None,
    allowed_gpus: Optional[list[str]] = None,
    allowed_cpus: Optional[list[str]] = None,
    profile: Optional[str] = None,
    workflow_name: Optional[str] = None,
    workflow_version: Optional[str] = None,
    run_args: Optional[list] = None,
    run_kwargs: Optional[list] = None,
    run_input_artifact_hash: Optional[str] = None,
):
    if isinstance(execution_mode, str):
        execution_mode = ExecutionMode(execution_mode)

    if entrypoint_file and entrypoint_hash:
        raise RuntimeError(
            "run: cannot provide both entrypoint_file and entrypoint_hash"
        )

    if run_input_artifact_hash and (run_args or run_kwargs):
        raise RuntimeError(
            "run: cannot provide both input_artifact_hash and run_args/run_kwargs"
        )

    if run_args or run_kwargs:
        run_input_artifact_hash = push_artifact(
            {"args": run_args, "kwargs": run_kwargs}
        )

    if entrypoint_file:
        workflow_tag, _ = build_workflow(
            entrypoint=entrypoint_file,
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            local_only=execution_mode
            in [ExecutionMode.local, ExecutionMode.classical_local_quantum_remote],
        )
    elif entrypoint_hash:
        workflow_tag = get_workflow_from_hash(entrypoint_hash)

    workflow_plan = plan_workflow(
        workflow_tag=workflow_tag,
        profile_name=profile,
        allowed_cpus=allowed_cpus,
        allowed_gpus=allowed_gpus,
        allowed_qpus=allowed_qpus,
        execution_mode=execution_mode,
    )

    # As assignment is memory-only in daemon for now, push assignment directly in create_workflow_run
    # workflow_obj = deploy_workflow(
    #     workflow_tag=workflow_tag,
    #     workflow_assignments=workflow_assignments,
    # )

    run_obj, artifacts = create_workflow_run(
        workflow_plan=workflow_plan,
        run_input_artifact_hash=run_input_artifact_hash,
        auto_start_daemon=True,
    )

    return run_obj, artifacts


def fix():
    raise NotImplementedError()
