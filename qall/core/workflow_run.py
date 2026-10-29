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
from __future__ import annotations

import datetime
import logging
import uuid

from typing import Optional
from pathlib import Path

from qall.object import (
    WorkflowRun,
    WorkflowRunStatus,
    apply_resource_overrides,
    DaemonStatus,
)
from qall.specification.workflow import WorkflowSpec
from qall.registry import BlockRegistry, RegistryCredentials
from qall.provider import (
    WorkflowProviderClient,
    ProviderCredentials,
    get_provider_client_by_name,
    get_provider_login_credentials,
)
from qall.core.registry import push_workflow_on_registry
from qall.core.workflow import create_workflow, run_workflow, stop_workflow
from qall.core.daemon import (
    get_daemon_status,
    run_task,
    start_daemon,
    stop_daemon,
    apply_resource_assignments,
)
from qall.core.dataloader import (
    provision_dataloader_files_for_dag,
    cleanup_dataloader_files,
)
from qall.core.config import init_config
from qall.config import (
    get_local_configuration,
    get_default_configuration,
    config_exists,
)
from qall.resolver import resolve_workflow_resources
from qall.provider.qc import WorkerCatalog
from qall.provider.qc.local import register_local_workers
from qall.provider.qc.scaleway import register_scaleway_workers

logger = logging.getLogger(__name__)


def _artifact_show_hints(artifacts) -> str:
    """Copy-paste ``qall artifact show <hash>`` hints for each generated artifact.

    Each hint lets the user launch the CLI command that deserializes and prints
    the matching local artifact, optionally annotated with the producing task.
    Artifacts without a usable content hash are skipped.
    """
    hints = ["To show an artifact, run the following command(s):"] if artifacts else []
    for artifact in artifacts or []:
        artifact_hash = getattr(artifact, "hash", None)
        if not artifact_hash:
            continue

        hint = f"\n\t-> 'qall artifact show {artifact_hash}'"
        hints.append(hint)

    return "".join(hints)


def create_workflow_run(
    entrypoint: str,
    workflow_name: Optional[str] = None,
    workflow_version: Optional[str] = None,
    profile_name: Optional[str] = None,
    input_artifact_hash: Optional[str] = None,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
    local_only: bool = False,
    auto_start_daemon: bool = False,
    allowed_qpus: Optional[list[str]] = None,
    allowed_cpus: Optional[list[str]] = None,
    allowed_gpus: Optional[list[str]] = None,
    **kwargs,
) -> WorkflowRun:
    """
    Launches the full Workflow execution lifecycle from the base file definition.
    Parses Workflow and Tasks -> Push to registry -> Provision resources according to the profile
    -> Starts the Workflow -> Execute the Workflow
    """

    workflow_version = workflow_version or "latest"
    workflow_name = workflow_name or Path(entrypoint).stem

    try:
        workflow_spec = WorkflowSpec(entrypoint)
        tag_uri, dag = push_workflow_on_registry(
            workflow_spec=workflow_spec,
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            registry_client=registry_client,
            registry_credentials=registry_credentials,
            local_only=local_only,
        )
    except Exception as e:
        raise RuntimeError(
            f"Couldn't push workflow on registry '{registry_client.remote_domain if registry_client else "local"}'.\nReason: {e}"
        )

    provider_credentials = provider_credentials or get_provider_login_credentials()

    if not provider_credentials:
        active_provider = "local"
    else:
        active_provider = provider_credentials.provider

    if not local_only and not provider_credentials:
        raise RuntimeError(
            "You must be logged in to execute workflows remotely. "
            "Run `qall login <provider>` or use `--local`."
        )

    if config_exists():
        local_config = get_local_configuration()
    else:
        local_config = init_config(active_provider)

    profile = (
        local_config.get_profile(profile_name)
        if profile_name
        else local_config.get_default_profile()
    )

    if profile.provider != "local" and not provider_credentials:
        logging.warning(
            f"profile is targetting {profile.provider} but not loggin, considering default local profile instead"
        )

        active_provider = "local"
        default_config = get_default_configuration(active_provider)
        profile = default_config.get_default_profile()

    if profile.provider == "local":
        active_provider = "local"

    if not profile:
        raise RuntimeError(
            f"No profile found (requested: '{profile_name or 'default'}') "
            f"in configuration. Available: {list(local_config.profiles.keys())}"
        )

    profile = apply_resource_overrides(
        profile=profile,
        allowed_qpu=allowed_qpus,
        allowed_cpu=allowed_cpus,
        allowed_gpu=allowed_gpus,
    )

    available_resources = []

    if active_provider != "local" and provider_credentials:
        provider_client = provider_client or get_provider_client_by_name(
            active_provider
        )
        if not provider_client.login(provider_credentials):
            raise RuntimeError(
                f"Failed to authenticate against provider '{active_provider}'."
            )
        available_resources = provider_client.list_resources()

    resource_assignments = resolve_workflow_resources(
        task_dag=dag,
        profile=profile,
        available_resources=available_resources,
        replace_to_local=local_only,
    )

    worker_definitions = _get_provider_workers(active_provider)

    if local_only:
        daemon_status = get_daemon_status()
        daemon_is_already_running = daemon_status.status == DaemonStatus.RUNNING

        if not daemon_is_already_running:
            if not auto_start_daemon:
                raise RuntimeError(
                    "No qall daemon running. Start it first, or set auto_start_daemon=True."
                )
            logger.info("Daemon not running. Starting local daemon...")
            start_daemon(detach=True)

        if worker_definitions or resource_assignments:
            apply_resource_assignments(
                worker_definitions=worker_definitions,
                resource_assignments=resource_assignments,
            )

        dataloader_files = provision_dataloader_files_for_dag(dag)

        start = datetime.datetime.now()
        try:
            artifacts = run_task(
                task_hash=dag.root_hash,
                input_artifact_hash=input_artifact_hash,
                provider_credentials=provider_credentials,
            )
            stop = datetime.datetime.now()

            logger.info(
                "Workflow done. "
                + (
                    f"Generated artifacts:\n\t{str("\n\t".join([str(a) for a in artifacts]))}"
                    if artifacts
                    else "No artifacts generated."
                )
            )

            # QoL: let the user launch `qall artifact show <hash>` to display the
            # actual output(s), annotated with the entrypoint task that produced them.
            hints = _artifact_show_hints(artifacts)
            if hints:
                logger.info(hints)

            workflow_run = WorkflowRun(
                id=str(uuid.uuid4()),
                workflow_id=str(tag_uri),
                status=WorkflowRunStatus.DONE,
                created_at=start,
                started_at=start,
                finished_at=stop,
            )
        except Exception as e:
            logger.error(f"Error running workflow `{entrypoint}`: {e}")
            workflow_run = WorkflowRun(
                id=str(uuid.uuid4()),
                workflow_id=str(tag_uri),
                status=WorkflowRunStatus.ERROR,
                created_at=start,
                started_at=start,
                finished_at=datetime.datetime.now(),
            )
        finally:
            cleanup_dataloader_files(dataloader_files)

            if not daemon_is_already_running and auto_start_daemon:
                stop_daemon()

    else:
        workflow = create_workflow(
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            registry_client=registry_client,
            registry_credentials=registry_credentials,
            provider_client=provider_client,
            provider_credentials=provider_credentials,
            profile=profile,
        )

        if not workflow:
            raise RuntimeError(f"Couldn't create workflow from '{entrypoint}'.")

        workflow_run = run_workflow(
            workflow=workflow,
            provider_client=provider_client,
            provider_credentials=provider_credentials,
            input_artifact_hash=input_artifact_hash,
            **kwargs,
        )

        if not workflow_run:
            raise RuntimeError(
                f"Couldn't start workflow run for workflow '{workflow.id}'."
            )

    return workflow_run


def stop_workflow_run(
    workflow_run_id: str,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
):
    provider_credentials = provider_credentials or get_provider_login_credentials()
    provider_client = provider_client or get_provider_client_by_name(
        provider_credentials.provider
    )

    stop_workflow(
        workflow_run_id,
        provider_client=provider_client,
        provider_credentials=provider_credentials,
    )


def fix_workflow_run(
    entrypoint: str,
    workflow_run_id: str,
    registry_client: Optional[BlockRegistry] = None,
    registry_credentials: Optional[RegistryCredentials] = None,
    provider_client: Optional[WorkflowProviderClient] = None,
    provider_credentials: Optional[ProviderCredentials] = None,
) -> WorkflowRun:
    raise NotImplementedError()


def _get_provider_workers(provider: str):
    if not provider:
        logger.info("No worker provider defined.")
        return

    catalog = WorkerCatalog()

    if provider == "local":
        catalog = register_local_workers(catalog)
    elif provider == "scaleway":
        catalog = register_scaleway_workers(catalog)
    else:
        raise RuntimeError(f"Worker provider {provider} is not supported.")

    if not catalog:
        raise RuntimeError("could not load catalog properly")

    return catalog.get_by_provider(provider)
