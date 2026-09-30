from google.api import annotations_pb2 as _annotations_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import (
    ClassVar as _ClassVar,
    Mapping as _Mapping,
    Optional as _Optional,
    Union as _Union,
)

DESCRIPTOR: _descriptor.FileDescriptor

class Error(_message.Message):
    __slots__ = ("code", "message")

    class Code(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        UNKNOWN_ERROR: _ClassVar[Error.Code]
        INVALID_PROGRAM: _ClassVar[Error.Code]
        UNSUPPORTED_FORMAT: _ClassVar[Error.Code]
        INVALID_RESOURCE: _ClassVar[Error.Code]
        SESSION_EXPIRED: _ClassVar[Error.Code]
        QPU_UNAVAILABLE: _ClassVar[Error.Code]
        PROVIDER_ERROR: _ClassVar[Error.Code]
        EXECUTION_FAILED: _ClassVar[Error.Code]

    UNKNOWN_ERROR: Error.Code
    INVALID_PROGRAM: Error.Code
    UNSUPPORTED_FORMAT: Error.Code
    INVALID_RESOURCE: Error.Code
    SESSION_EXPIRED: Error.Code
    QPU_UNAVAILABLE: Error.Code
    PROVIDER_ERROR: Error.Code
    EXECUTION_FAILED: Error.Code
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    code: Error.Code
    message: str
    def __init__(
        self,
        code: _Optional[_Union[Error.Code, str]] = ...,
        message: _Optional[str] = ...,
    ) -> None: ...

class QuantumContext(_message.Message):
    __slots__ = ("id", "resource", "provider", "configuration", "metadata")

    class ConfigurationEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(
            self, key: _Optional[str] = ..., value: _Optional[str] = ...
        ) -> None: ...

    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(
            self, key: _Optional[str] = ..., value: _Optional[str] = ...
        ) -> None: ...

    ID_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    CONFIGURATION_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    id: str
    resource: str
    provider: str
    configuration: _containers.ScalarMap[str, str]
    metadata: _containers.ScalarMap[str, str]
    def __init__(
        self,
        id: _Optional[str] = ...,
        resource: _Optional[str] = ...,
        provider: _Optional[str] = ...,
        configuration: _Optional[_Mapping[str, str]] = ...,
        metadata: _Optional[_Mapping[str, str]] = ...,
    ) -> None: ...

class CreateContextRequest(_message.Message):
    __slots__ = ("resource", "configuration", "metadata")

    class ConfigurationEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(
            self, key: _Optional[str] = ..., value: _Optional[str] = ...
        ) -> None: ...

    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(
            self, key: _Optional[str] = ..., value: _Optional[str] = ...
        ) -> None: ...

    RESOURCE_FIELD_NUMBER: _ClassVar[int]
    CONFIGURATION_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    resource: str
    configuration: _containers.ScalarMap[str, str]
    metadata: _containers.ScalarMap[str, str]
    def __init__(
        self,
        resource: _Optional[str] = ...,
        configuration: _Optional[_Mapping[str, str]] = ...,
        metadata: _Optional[_Mapping[str, str]] = ...,
    ) -> None: ...

class CreateContextResponse(_message.Message):
    __slots__ = ("context", "error")
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    context: QuantumContext
    error: Error
    def __init__(
        self,
        context: _Optional[_Union[QuantumContext, _Mapping]] = ...,
        error: _Optional[_Union[Error, _Mapping]] = ...,
    ) -> None: ...

class RunRequest(_message.Message):
    __slots__ = ("program", "parameters", "context")
    PROGRAM_FIELD_NUMBER: _ClassVar[int]
    PARAMETERS_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    program: QuantumProgram
    parameters: QuantumProgramParameters
    context: QuantumContext
    def __init__(
        self,
        program: _Optional[_Union[QuantumProgram, _Mapping]] = ...,
        parameters: _Optional[_Union[QuantumProgramParameters, _Mapping]] = ...,
        context: _Optional[_Union[QuantumContext, _Mapping]] = ...,
    ) -> None: ...

class RunResponse(_message.Message):
    __slots__ = ("result", "context", "error")
    RESULT_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    result: QuantumProgramResult
    context: QuantumContext
    error: Error
    def __init__(
        self,
        result: _Optional[_Union[QuantumProgramResult, _Mapping]] = ...,
        context: _Optional[_Union[QuantumContext, _Mapping]] = ...,
        error: _Optional[_Union[Error, _Mapping]] = ...,
    ) -> None: ...

class QuantumProgram(_message.Message):
    __slots__ = ("format", "version", "payload")
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    format: str
    version: str
    payload: bytes
    def __init__(
        self,
        format: _Optional[str] = ...,
        version: _Optional[str] = ...,
        payload: _Optional[bytes] = ...,
    ) -> None: ...

class QuantumProgramParameters(_message.Message):
    __slots__ = ("format", "version", "payload")
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    format: str
    version: str
    payload: bytes
    def __init__(
        self,
        format: _Optional[str] = ...,
        version: _Optional[str] = ...,
        payload: _Optional[bytes] = ...,
    ) -> None: ...

class QuantumProgramResult(_message.Message):
    __slots__ = ("format", "version", "payload")
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    format: str
    version: str
    payload: bytes
    def __init__(
        self,
        format: _Optional[str] = ...,
        version: _Optional[str] = ...,
        payload: _Optional[bytes] = ...,
    ) -> None: ...

class GetCapabilitiesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Capabilities(_message.Message):
    __slots__ = ("provider", "input_format", "output_format")
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    INPUT_FORMAT_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FORMAT_FIELD_NUMBER: _ClassVar[int]
    provider: str
    input_format: str
    output_format: str
    def __init__(
        self,
        provider: _Optional[str] = ...,
        input_format: _Optional[str] = ...,
        output_format: _Optional[str] = ...,
    ) -> None: ...

class CloseContextRequest(_message.Message):
    __slots__ = ("context",)
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    context: QuantumContext
    def __init__(
        self, context: _Optional[_Union[QuantumContext, _Mapping]] = ...
    ) -> None: ...
