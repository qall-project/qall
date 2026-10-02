FROM python:3.13-slim AS builder

WORKDIR /build

COPY --from=docker.io/astral/uv:0.8.17 /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
COPY qall ./qall

RUN uv sync --locked --no-dev

FROM python:3.13-slim

WORKDIR /qall-workspace

COPY --from=builder /build/.venv /qall-workspace/.venv
COPY --from=builder /build/qall /qall-workspace/qall

ENV PATH="/qall-workspace/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

CMD ["python"]