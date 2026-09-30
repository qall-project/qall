# Qall

A python tool for modern hybrid and quantum workflows.

## Install

This project is managed using uv.

If you simply want to use it, install it with pip:
```bash
uv pip install .
# Or the slower but pip-only option
pip install .
qall --help
```

In order to contribute, you shall sync dependencies:
```bash
uv sync
uv run qall --help
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