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

from concurrent import futures

from qio.core import QuantumProgram, QuantumProgramResult, QuantumComputationParameters

from ..protobuf.qc_worker_api_v1 import (
    qc_worker_api_v1_pb2 as pb2,
)
from ..protobuf.qc_worker_api_v1 import (
    qc_worker_api_v1_pb2_grpc as pb2_grpc,
)

from qall.interop.mapping import (
    qio_program_to_native_program,
    native_result_to_qio_result,
)
from qall.provider.login import get_credentials_from_env

from ..context import QuantumContext
from .qc_worker import QuantumWorker


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


class QuantumWorkerApi(pb2_grpc.ApiServicer):
    def __init__(
        self,
        worker: QuantumWorker,
    ) -> None:
        self.__worker = worker

    def CreateContext(
        self,
        request: pb2.CreateContextRequest,
        grpc_context: grpc.ServicerContext,
    ) -> pb2.QuantumContext:

        try:
            creds = get_credentials_from_env()
            resource = creds.pop("QALL_PROVIDER_TARGET_RESOURCE", None)

            context = QuantumContext(
                configuration=dict(request.configuration),
                metadata=dict(request.metadata),
            )

            context = self.__worker.create_context(
                resource=resource, context=context, **creds
            )

            return context_to_proto(context)

        except Exception as exc:
            grpc_context.abort(
                grpc.StatusCode.INTERNAL,
                str(exc),
            )

    def Run(
        self,
        request: pb2.RunRequest,
        grpc_context: grpc.ServicerContext,
    ) -> pb2.RunResponse:

        try:
            context = context_from_proto(request.context)

            program = self._deserialize_program(request.program)

            params = self._deserialize_params(request.parameters)

            native_program = qio_program_to_native_program(
                program, self.__worker.capabilities.input_format
            )

            result = self.__worker.run(
                program=native_program,
                shots=params.shots,
                context=context,
                **params.options,
            )

            qio_result = native_result_to_qio_result(result)

            return pb2.RunResponse(
                result=self._serialize_result(qio_result),
                context=context_to_proto(context),
            )
        except Exception as exc:
            print("exception occured in worker.run", exc)

            return pb2.RunResponse(
                error=pb2.Error(
                    code=pb2.Error.EXECUTION_FAILED,
                    message=str(exc),
                )
            )

    def CloseContext(
        self,
        request: pb2.CloseContextRequest,
        grpc_context: grpc.ServicerContext,
    ) -> pb2.QuantumContext:

        try:
            context = context_from_proto(request.context)

            context = self.__worker.close_context(context)

            return context_to_proto(context)

        except Exception as exc:
            grpc_context.abort(
                grpc.StatusCode.INTERNAL,
                str(exc),
            )

    def GetCapabilities(
        self,
        request: pb2.GetCapabilitiesRequest,
        grpc_context: grpc.ServicerContext,
    ) -> pb2.Capabilities:

        c = self.__worker.capabilities

        return pb2.Capabilities(
            input_format=c.input_format, output_format=c.output_format
        )

    def _deserialize_program(
        self,
        proto: pb2.QuantumProgram,
    ) -> QuantumProgram:
        if proto.format == "qio":
            return QuantumProgram.from_json_str(proto.payload.decode("utf-8"))
        raise NotImplementedError

    def _deserialize_params(
        self,
        proto: pb2.QuantumProgramParameters,
    ) -> dict:
        if proto.format == "qio":
            return QuantumComputationParameters.from_json_str(
                proto.payload.decode("utf-8")
            )
        raise NotImplementedError

    def _serialize_result(
        self,
        result: QuantumProgramResult,
    ) -> pb2.QuantumProgramResult:

        return pb2.QuantumProgramResult(
            format="qio",
            version="1",
            payload=result.to_json_str().encode("utf-8"),
        )

    def _qio_program_to_native_program(
        self,
        program: QuantumProgram,
        worker_input_format: str,
    ):
        mapping = {
            "qiskit.QuantumCircuit": program.to_qiskit_circuit(),
            "qiskit": program.to_qiskit_circuit(),
            "cirq.Circuit": program.to_cirq_circuit(),
            "cirq": program.to_cirq_circuit(),
            "cudaq.PyKernel": program.to_cudaq_kernel(),
            "cudaq": program.to_cudaq_kernel(),
            "mimiqcircuits.Circuit": program.to_mimiq_circuit(),
            "mimiq": program.to_mimiq_circuit(),
            "qasm2": program.to_qasm2_circuit(),
            "qio.QuantumProgram": program,
            "qio": program,
        }

        return mapping.get(worker_input_format, program)

    def _native_result_to_qio_result(
        self,
        result,
        worker_output_format: str,
    ) -> QuantumProgramResult:
        mapping = {
            "qiskit.result.Result": QuantumProgramResult.from_qiskit_result(result),
            "qiskit": QuantumProgramResult.from_qiskit_result(result),
            "cirq.Result": QuantumProgramResult.from_cirq_result(result),
            "cirq": QuantumProgramResult.from_cirq_result(result),
            "cudaq.SampleResult": QuantumProgramResult.from_cudaq_sample_result(result),
            "cudaq": QuantumProgramResult.from_cudaq_sample_result(result),
            "mimiqcircuits.QCSResults": QuantumProgramResult.from_mimiq_qcsr(result),
            "mimiq": QuantumProgramResult.from_mimiq_qcsr(result),
            "qio.QuantumProgramResult": result,
            "qio": result,
        }

        return mapping.get(worker_output_format, result)

    def serve(
        self,
        port: str | int,
        host: str = "0.0.0.0",
    ) -> grpc.Server:
        server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=10),
        )
        pb2_grpc.add_ApiServicer_to_server(
            self,
            server,
        )

        address = f"{host}:{port}"
        server.add_insecure_port(address)

        print(f"[WorkerExecutor] Starting gRPC server on {address}")
        server.start()

        try:
            server.wait_for_termination()
        finally:
            print("[WorkerExecutor] Stopping gRPC server")
            server.stop(grace=5)
