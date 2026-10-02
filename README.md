# Qall: Composable execution for hybrid computing

Qall is an open-source framework for defining, packaging and executing hybrid workflows across heterogeneous compute resources, from CPUs and GPUs to quantum processors (QPU) and emulators.

Qall separates what a computation needs from where it runs, making workflows **portable**, **reproducible** and **reusable across infrastructure**.

Qall was initially developed around hybrid quantum-classical workloads, where classical and quantum resources must work together as part of a single computation.

[![PyPI version](https://badge.fury.io/py/qall.svg)](https://badge.fury.io/py/qall)
[![CI](https://github.com/qall-project/qall/actions/workflows/ci.yml/badge.svg)](https://github.com/qall-project/qall/actions)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

## Why Qall?
Hybrid workloads increasingly combine different types of compute -CPU, GPU, QPU- alongside storage, network, infrastructure management.

Today, connecting these resources often means managing provider SDKs, environments, credentials, queues, intermediate data and execution state yourself.

Qall provides a common execution model:
- **Tasks** describe units of computation and their resource requirements.
- **Workflows** compose tasks into computation graphs.
- **Resource profiles** map abstract requirements to available infrastructure.
- **Artifacts** and **checkpoints** support persistence and partial recomputation.
- **Workers** provide adapters for specific execution backends.
- A content-addressed **registry** makes computations versionable and reusable.

## Quickstart

Install Qall SDK & CLI:

```bash
pip install qall
```

Write a hybrid workflow:

```Python
from qall import task, workflow, run

@task(resource={"min_cpu": 2})
def prepare_data():
    return [0.1, 0.2, 0.3]

@workflow
def main():
    data = prepare_data()
    print(f"Prepared data: {data}")
```

Run it locally:

```bash
qall run my_workflow.py --local
```

Run it remotely :

```bash
qall login scaleway --secret-key=X --project-id=Y

qall run my_workflow.py
```

The same execution model is designed to extend from local development to managed heterogeneous infrastructure.

## Architecture

Qall is composed of a few independent building blocks:

| Component | Repository | Role |
|---|---|---|
| **Qall SDK & CLI** | [`qall`](https://github.com/qall-project/qall) | Define and run workflows |
| **Qall Registry** | [`qall-registry`](https://github.com/qall-project/qall-registry) | Store and distribute computation objects |
| **Qall Daemon** | [`qall-daemon`](https://github.com/qall-project/qall-daemon) | Execute workflows and manage task/worker runtimes |

The SDK and CLI provide the user-facing interface, while the registry and daemon provide the infrastructure required to distribute and execute computations.

## Design principles

### Separate computation from infrastructure

Workflows describe **requirements**, not necessarily physical resources.

```python
@task(
    resource={
        "min_cpu": 2,
        "min_memory_gb": 16,
    }
)
def preprocess():
    ...
```

The actual resource can be selected later according to the active execution profile.

### Computations as reusable artifacts

Qall represents workflows as content-addressed computation graphs.

This enables:

- deterministic versioning;
- deduplication;
- workflow sharing;
- partial recomputation;
- reusable computation components.

### Heterogeneous execution

The same workflow model can combine:

- CPU workloads;
- GPU workloads;
- quantum emulators;
- QPUs;
- other specialized execution backends.

Quantum computing is one of the first use cases driving this model.

## Project status

Qall is an **early-stage open-source project** under active development.

The APIs and execution model are evolving. The project is currently intended primarily for experimentation, development and feedback from the hybrid computing community.


## Folder hierarchy
`sdk`: SDK API used for workflow development
- Must call `core` as possible
- Never technology dependant

`cli`: CLI implementation for workflow deployment:
- Mostly CLI commodities and display
- Must call `core` as possible
- Never technology dependant
- Only manipulate `object` objects

`core`: High level business logic
- Never technology dependant
- Handle every default value
- Only manipulate `object`, `core` and mid level `other` objects

`object`: Data transfert objects (DTO) definition between
- Never technology dependant

others (`codec`, `daemon`, `provider`, `registry`, `specification`...):
- Provide mid and low level implementation to be used by `core`
- Mid level must use `object` object as possible
- Can be technology dependant (`qall-registry-client`, `qall-daemon-client`, `lmdb`, `pip`...)