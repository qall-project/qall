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

```python
@task(min_cpu=2, min_memory_gb=16)
```

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

## Call graph analysis (pyan3)

The `specification` layer builds each workflow's call graph with **pyan3
(`>= 2.9.0,<3`)** via its in-memory `from_sources` API: `qall/specification/utils.py`
feeds the workflow's user sources as `(source_text, fully_qualified_module_name)`
pairs derived from `sys.modules` (see `_discover_user_sources`). Discovery is
import-based rather than path-glob based, so user helper modules anywhere on the
filesystem that the workflow actually imports are included, while the stdlib,
installed site-packages and `qall` itself are excluded. Node/edge identity is
pyan's qualified name (`pkg.mod.func`); short task names are only used at the
registry/graph boundary. `tests/test_pyan_shapes.py` pins the pyan data-shape
contract.