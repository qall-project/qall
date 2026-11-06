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

# Dataloader configuration

Dataloaders are persisted through the same `LocalConfiguration` YAML machinery
as resource profiles (both accept `profiles`, `dataloaders` and `version`
sections), with an **opencode-style two-scope layering**:

| Scope | File | Precedence |
|---|---|---|
| global | `~/.config/qall/qall-config.yml` (env: `QALL_CONFIG_PATH`) | fallback |
| local | `./.qall.yml` (current project, env: `QALL_LOCAL_CONFIG_PATH`) | wins |

Name resolution is **local-first, then global**: `qall dataloader get/info/...`
looks for a required dataloader in the project's `.qall.yml` first and falls
back to the global file; if neither scope defines the name it cannot be
resolved. `qall dataloader add` writes to the **global** config by default; the
`--current-project` flag scopes the entry to the project's `.qall.yml` (a local
entry shadows a same-named global one).

Sensitive credentials never land in either YAML file: they are stored in the
host keyring under the scoped user `"{scope}:{name}"` and persisted as
self-describing `keyring://qall_dataloader/{scope}:{name}/{key}` placeholders.
A legacy single-file global JSON (`~/.config/qall/qall-config.json`) is
migrated best-effort into the global YAML on first access (the old file is left
in place).

The `qall dataloader add/update` CLI prompts for each credential (Access key,
Secret key, Endpoint URL...) by default instead of only accepting them as flags,
so secrets don't leak into shell history. Flags still work for automation and
skip their matching prompt; `--no-prompt` disables prompting entirely. For
`update`, leaving a prompt empty keeps the currently stored value.

# Dataloader runtime (mounting)

A dataloader is bound into a task as a **real kernel mount**, so task code reads
and writes plain POSIX paths — no import hooks, no monkeypatching.

- `dst` is a root-based name: `qall dataloader add s3prod s3://bucket/prefix data`
  exposes the bucket at **`/data`** inside every task that declares the
  dataloader (`dst` is normalised: `./data/`, `data` and `/data/` are the same;
  empty, `/` and `..` are rejected).
- Mounting happens **exclusively in the daemon**, when a task run is created. The
  client resolves the credentials from the host keyring and sends them on the
  run's `CreateTaskRun` request; the daemon creates an `rclone` Docker volume for
  each `(workflow_run_id, dataloader_name)` pair and mounts it into the task
  container. The volume is released when the last task of the run using it ends.
- `file://` (and bare absolute) sources are not remote: the daemon bind-mounts
  them read-only at the same path, with no host dependency.

Host prerequisites (only for remote sources):

| Dependency | Why | Notes |
|---|---|---|
| `fuse3` (`/dev/fuse`, `fusermount3`) | rclone serves the volume through FUSE | On macOS it lives inside the Docker Desktop VM, nothing to install on the host |
| `rclone` Docker volume plugin (alias `rclone`) | the volume driver | `docker plugin install rclone/docker-volume-rclone:<arch> --alias rclone --grant-all-permissions` |

`qall dataloader setup --check` reports their state and `qall dataloader setup`
installs whatever is missing (never implicit: running a workflow only *checks*
and raises an actionable `DataloaderDependencyError`). The same is available
programmatically through `qall.setup_dataloader_host_dependencies(...)` /
`qall.daemon.dependencies.install_dataloader_dependencies(...)`. The daemon
re-checks at runtime and reports a structured `FailedPrecondition` error if the
plugin disappeared, so a broken host never turns into a raw Docker panic or a
hang.

The daemon gets a host directory for this bookkeeping at
`<HOST_VOLUMES_ROOT>/dataloaders` (`/tmp/qall/dataloaders` by default,
`QALL_HOST_VOLUMES_ROOT` to override), bind-mounted 1:1 into the containerised
daemon (`-host-volumes-root`). The daemon creates one sub-directory per
`(workflow_run_id, dataloader_name)` there and uses it as the rclone VFS cache
directory.

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

pyan3's loggers are routed through qall's own logger at package init
(`qall/__init__.py::_configure_pyan_logging`): their output shares qall's
`[...] LEVEL | name | message` format instead of leaking raw to the root logger.
Verbosity is gated behind qall's — `QALL_LOGGING_LEVEL=DEBUG` surfaces pyan's
INFO/DEBUG records, otherwise pyan is quiet at WARNING+. Pinned by
`tests/test_pyan_logging.py`.