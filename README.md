# Hybrid computing as a Service

## Protobuf

To re-generate registry client/server API:

```bash
cd protobuf/

make registry
```

To re-generate daemon client/server API:

```bash
cd protobuf/

make daemon
```

## Registry server

To test registry server:
```bash
cd qall-registry-server/

make test
```

To build registry server:
```bash
cd qall-registry-server/

make build
```

To start local instructure
```bash
cd infrastructure/local/

make start
```

## Registry client

To install registry client:
```bash
cd qall-registry-client/

pip install .
```

To test registry client:
```bash
cd qall-registry-client/

export qall_REGISTRY_URL=localhost:50051; pytest -vvv tests/
```

## Daemon server

To run daemon server:
```bash
make build

qall daemon start
```

## Daemon client

To install daemon client:
```bash
cd qall-daemon-client/

pip install .
```

## Scaleway HCaaS client
TODO

## qall (SDK)

To install qall sdk:
```bash
cd qall/

pip install .
```

To push a project to the registry:
```bash
cd qall/

pip install .

qall registry push examples/basic_hierarchy/my_worflow.py

qall daemon start

qall daemon run <root hash>
```