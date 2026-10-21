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
from __future__ import annotations

from typing import List, Optional

from dataclasses import dataclass, field, replace
from dataclasses_json import dataclass_json


@dataclass_json
@dataclass(frozen=True)
class AllowedResourceCollection:
    qpu: list[str] = field(default_factory=list)
    gpu: list[str] = field(default_factory=list)
    cpu: list[str] = field(default_factory=list)


@dataclass_json
@dataclass(frozen=True)
class ResourceProfile:
    provider: str
    match_strategy: str
    allowed: AllowedResourceCollection
    default: bool


def apply_resource_overrides(
    profile: ResourceProfile,
    allowed_qpu: Optional[List[str]] = None,
    allowed_cpu: Optional[List[str]] = None,
    allowed_gpu: Optional[List[str]] = None,
) -> ResourceProfile:
    """
    Overrides the allowed resources in a frozen ResourceProfile with explicit CLI flags.
    """
    if not any([allowed_qpu, allowed_cpu, allowed_gpu]):
        return profile

    new_qpu = allowed_qpu if allowed_qpu is not None else profile.allowed.qpu
    new_cpu = allowed_cpu if allowed_cpu is not None else profile.allowed.cpu
    new_gpu = allowed_gpu if allowed_gpu is not None else profile.allowed.gpu

    new_allowed = AllowedResourceCollection(
        qpu=list(new_qpu),
        cpu=list(new_cpu),
        gpu=list(new_gpu),
    )

    return replace(profile, allowed=new_allowed)
