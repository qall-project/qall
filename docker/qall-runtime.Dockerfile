FROM docker-proxy.internal.scaleway.com/python:3.13-slim

WORKDIR /qall-workspace

RUN apt-get update && apt-get install -y curl ca-certificates && rm -rf /var/lib/apt/lists/*

ADD https://astral.sh/uv/install.sh /uv-install.sh
RUN sh /uv-install.sh && rm /uv-install.sh

COPY ./qall /qall-workspace/qall
COPY ./qall-daemon-client /qall-workspace/qall-daemon-client
COPY ./qall-registry-client /qall-workspace/qall-registry-client