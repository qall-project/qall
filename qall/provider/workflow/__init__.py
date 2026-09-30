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
import logging

from typing import Dict, Type, Callable, List

from .provider_client import WorkflowProviderClient

__PROVIDER_REGISTRY: Dict[str, WorkflowProviderClient] = {}

logger = logging.getLogger(__name__)


def provider(name: str) -> Callable:
    """
    DECORATOR (for packages): Registers a new WorkflowProviderClient class.
    """

    def decorator(cls: Type[WorkflowProviderClient]) -> Type[WorkflowProviderClient]:
        if not issubclass(cls, WorkflowProviderClient):
            raise TypeError(
                f"Class {cls.__name__} must inherit from WorkflowProviderClient"
            )

        if name in __PROVIDER_REGISTRY:
            raise RuntimeError(f"cannot redefined provider '{name}'")

        try:
            instance = cls(name)
            instance.name = name
            __PROVIDER_REGISTRY[name] = instance
        except Exception as e:
            raise RuntimeError(f"Failed to instantiate provider '{name}': {e}")

        return cls

    return decorator


def get_provider_client_by_name(name: str) -> WorkflowProviderClient:
    provider = __PROVIDER_REGISTRY.get(name, None)

    if not provider:
        raise RuntimeError(f"cannot find provider with name {provider}")

    return provider
