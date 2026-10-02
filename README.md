# Qall: Composable Computation for Hybrid Quantum Workflows

[![PyPI version](https://badge.fury.io/py/qall.svg)](https://badge.fury.io/py/qall)
[![CI](https://github.com/qall-project/qall/actions/workflows/ci.yml/badge.svg)](https://github.com/qall-project/qall/actions)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Qall is an open-source framework designed to package, orchestrate, and execute hybrid quantum-classical workflows using content-addressed computation graphs.

## Quickstart

### 1. Install Qall SDK & CLI
```bash
pip install qall
```

### 2. Write a hybrid workflow

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

### 3. Write a hybrid workflow

```bash
qall run my_workflow.py --local
```

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