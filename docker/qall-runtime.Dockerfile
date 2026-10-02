FROM python:3.13-slim AS builder

WORKDIR /build

COPY --from=docker.io/astral/uv:0.11.29 /uv /uvx /bin/

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY qall ./qall

RUN uv build --wheel

FROM python:3.13-slim

WORKDIR /qall-workspace

COPY --from=builder /build/dist/*.whl /tmp/qall.whl

RUN pip install --no-cache-dir /tmp/qall.whl \
    && rm /tmp/qall.whl

ENV PYTHONUNBUFFERED=1

CMD ["python"]