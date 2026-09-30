# Copyright 2026 Scaleway
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import grpc

from typing import Any

from retry import retry
from qio.core import QuantumProgram, QuantumProgramResult, QuantumComputationParameters

from ..protobuf.qc_worker_api_v1 import (
    qc_worker_api_v1_pb2 as pb2,
)
from ..protobuf.qc_worker_api_v1 import (
    qc_worker_api_v1_pb2_grpc as pb2_grpc,
)

from qall.interop.mapping import (
    native_program_to_qio_program,
    qio_result_to_native_result,
)

from ..context import QuantumContext


def context_from_proto(
    proto: pb2.QuantumContext,
) -> QuantumContext:

    return QuantumContext(
        resource=proto.resource,
        configuration=dict(proto.configuration),
        metadata=dict(proto.metadata),
    )


def context_to_proto(
    context: QuantumContext,
) -> pb2.QuantumContext:

    return pb2.QuantumContext(
        resource=context.resource,
        configuration=context.configuration,
        metadata=context.metadata,
    )


class QuantumWorkerClient:
    """
    gRPC client for a remote QuantumWorker.

    This class deliberately contains no provider-specific logic.
    """

    def __init__(
        self,
        address: str,
        credentials: grpc.ChannelCredentials | None = None,
    ) -> None:

        if credentials is None:
            self._channel = grpc.insecure_channel(address)
        else:
            self._channel = grpc.secure_channel(
                address,
                credentials,
            )

        self._stub = pb2_grpc.ApiStub(self._channel)

    @retry(delay=2, tries=10)
    def create_context(
        self,
        context: QuantumContext,
    ) -> QuantumContext:

        response = self._stub.CreateContext(
            pb2.CreateContextRequest(
                resource=context.resource,
                configuration=context.configuration,
                metadata=context.metadata,
            )
        )

        return context_from_proto(response)

    @retry(delay=2, tries=10)
    def run(
        self,
        program: Any,
        shots: int,
        context: QuantumContext,
        output_format: str,
        **kwargs,
    ) -> tuple[Any, QuantumContext]:
        proto_context = context_to_proto(context)

        qio_program = native_program_to_qio_program(program)

        qio_params = self._native_params_to_qio(shots=shots, **kwargs)

        proto_program = self._serialize_program(qio_program)

        proto_params = self._serialize_params(qio_params)

        response = self._stub.Run(
            pb2.RunRequest(
                program=proto_program,
                context=proto_context,
                parameters=proto_params,
            )
        )

        if response.HasField("error"):
            raise RuntimeError(response.error.message)

        deser_result = self._deserialize_result(response.result)

        result = qio_result_to_native_result(deser_result, output_format)

        return (
            result,
            context_from_proto(response.context),
        )

    @retry(delay=2, tries=10)
    def close_context(
        self,
        context: QuantumContext,
    ) -> QuantumContext:

        response = self._stub.CloseContext(
            pb2.CloseContextRequest(
                context=context_to_proto(context),
            )
        )

        return context_from_proto(response)

    @retry(delay=2, tries=10)
    def get_capabilities(self) -> pb2.Capabilities:
        return self._stub.GetCapabilities(pb2.GetCapabilitiesRequest())

    def close(self) -> None:
        self._channel.close()

    def _deserialize_result(
        self,
        proto: pb2.QuantumProgramResult,
    ) -> QuantumProgramResult:
        print("deserialize result", proto)

        if proto.format == "qio":
            return QuantumProgramResult.from_json_str(proto.payload.decode("utf-8"))
        raise NotImplementedError

    def _serialize_program(
        self,
        program: QuantumProgram,
    ) -> pb2.QuantumProgram:

        return pb2.QuantumProgram(
            format="qio",
            version="1",
            payload=program.to_json_str().encode("utf-8"),
        )

    def _serialize_params(
        self,
        params: QuantumComputationParameters,
    ) -> pb2.QuantumProgramParameters:

        return pb2.QuantumProgramParameters(
            format="qio",
            version="1",
            payload=params.to_json_str().encode("utf-8"),
        )

    def _native_params_to_qio(
        self, shots: int, **kwargs
    ) -> QuantumComputationParameters:
        return QuantumComputationParameters(shots=shots, options=kwargs)
