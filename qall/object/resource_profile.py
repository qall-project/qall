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

from dataclasses import dataclass, field
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
