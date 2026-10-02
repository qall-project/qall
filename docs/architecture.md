# Architecture

Qall is composed of a few independent building blocks:

| Component | Repository | Role |
|---|---|---|
| **Qall SDK & CLI** | [`qall`](https://github.com/qall-project/qall) | Define and run workflows |
| **Qall Registry** | [`qall-registry`](https://github.com/qall-project/qall-registry) | Store and distribute computation objects |
| **Qall Daemon** | [`qall-daemon`](https://github.com/qall-project/qall-daemon) | Execute workflows and manage task/worker runtimes |

The SDK and CLI provide the user-facing interface, while the registry and daemon provide the infrastructure required to distribute and execute computations.

# Resource Profiles

Resource Profiles define the infrastructure available to Qall and how abstract
resource requirements are mapped to physical resources.

A workflow describes what a task needs:

@task(resource={"min_cpu": 2, "min_memory_gb": 16})

The Resource Profile determines where that task can run.

This keeps workflow definitions independent from a specific infrastructure
while allowing users or platform operators to control which resources are used.

# Package hierarchy

`sdk`: SDK API used for workflow execution
- Must call `core` as possible
- Never technology dependant

`cli`: CLI implementation for workflow execution and registry manipulation:
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

`data`: Contains worker adapter definition inventory
- Never technology dependant

others (`codec`, `daemon`, `provider`, `registry`, `specification`...):
- Provide mid and low level implementation to be used by `core`
- Mid level must use `object` object as possible
- Can be technology dependant (`qall-registry-client`, `qall-daemon-client`, `lmdb`, `pip`...)