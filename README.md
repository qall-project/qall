# Qall: Composable execution for hybrid computing

[![PyPI version](https://badge.fury.io/py/qall.svg)](https://badge.fury.io/py/qall)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Qall is an open-source framework for defining, packaging and executing hybrid workflows across heterogeneous compute resources, from CPUs and GPUs to quantum processors (QPU) and emulators.

Qall separates what a computation needs from where it runs, making workflows **portable**, **reproducible** and **reusable across infrastructure**.

Qall was initially developed around hybrid quantum-classical workloads, where classical and quantum resources must work together as part of a single computation.

## Why Qall?
Hybrid workloads increasingly combine different types of compute (CPU, GPU, QPU) alongside storage, network and infrastructure management.

```text
CPU loading
       │
       ▼
GPU preprocessing ───► QPU execution
       │                 │
       └───────┬─────────┘
               ▼
        CPU postprocessing
```

A single workload may need to move between CPU, GPU and QPU resources, while handling environments, credentials, queues, intermediate data and execution state.

Qall lets these steps be described as one computation, while infrastructure selection and execution are handled separately.

Qall provides a common execution model:
- **Tasks** & **Workflows**: define computations and compose them into graphs
- **Resource Profiles**: map abstract requirements to available infrastructure
- **Artifacts** & **Checkpoints**: persist intermediate state and enable partial recomputation
- **Workers**: connect computations to execution backends
- **Registry**: version and distribute computation objects

## Quickstart

Install Qall SDK & CLI:

```bash
pip install qall
```

Write your pythonic workflow:

```Python
from qall import task, workflow

def _get_value(val):
    return 0.5 * val

@task(resource={"min_cpu": 2})
def prepare_data(val : float):
    return [0.1, 0.2, 0.3] * _get_value(val)

@workflow
def main():
    data = prepare_data(0.5)
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

## Quantum / hybrid example

Qall can execute quantum circuits from within a classical workflow.

```python
from qall import task, workflow, run
import qiskit

@task(min_qubit=2, requirements=["qiskit"])
def execute_quantum(size):
    qc = qiskit.QuantumCircuit(size)
    qc.h(0)

    for i in range(1, size):
        qc.cx(i - 1, i)

    qc.measure_all()

    result = run(qc, shots=100)
    return result.get_counts()

@workflow
def main():
    result = execute_quantum(3)
    return result
```

The same workflow can combine classical computation and quantum execution without exposing provider-specific infrastructure in the workflow code.

`qall.run()`: hide the execution plumbing. Calling a quantum backend typically involves more than submitting a circuit: provider and SDK compatibility; authentication and credentials; backend discovery and selection; session or execution context creation; circuit submission and job management; queues and asynchronous execution provider-specific result formats; connection and execution state.

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

- deterministic versioning
- deduplication
- workflow sharing
- partial recomputation
- reusable computation components

### Heterogeneous execution

The same workflow model can combine:

- CPU workloads
- GPU workloads
- quantum emulators
- QPUs
- other specialized execution backends

Quantum computing is one of the first use cases driving this model.

## Who is Qall for?

Qall is designed for developers who want to stay hands-on with their workloads without having to build and maintain the infrastructure required to execute them.

You define the computation, its dependencies and its resource requirements. Qall takes care of packaging and execution across the available infrastructure.

At the same time, Qall keeps infrastructure decisions explicit and controllable through resource profiles, so users can control which resources their workloads can use rather than relying on opaque infrastructure decisions.

## Project status

Qall is an **early-stage open-source project** under active development.

The APIs and execution model are evolving. The project is currently intended primarily for experimentation, development and feedback from the hybrid computing community.

Qall is developed by **Scaleway's Quantum R&D team** as an open-source exploration of infrastructure for heterogeneous and hybrid computing.

The project is designed around open interfaces and infrastructure-agnostic abstractions, with the goal of making hybrid workloads easier to build, execute and share.