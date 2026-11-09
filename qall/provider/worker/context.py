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

import cloudpickle

from typing import Optional, Any
from dataclasses import dataclass, field


@dataclass
class QuantumContext:
    resource: Optional[str] = None
    configuration: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    bin_metadata: dict[str, bytes] = field(default_factory=dict)

    _unpickled_cache: dict[str, Any] = field(
        default_factory=dict, init=False, repr=False
    )

    def add_bin_field(self, field: str, value: Any):
        self.bin_metadata[field] = cloudpickle.dumps(value)

    def get_bin_field(self, field: str) -> Any:
        if field in self.bin_metadata:
            return cloudpickle.loads(self.bin_metadata[field])
        return None

    def __getitem__(self, key: str) -> Any:
        if key in self._unpickled_cache:
            return self._unpickled_cache[key]

        if key in self.bin_metadata:
            obj = cloudpickle.loads(self.bin_metadata[key])
            self._unpickled_cache[key] = obj
            return obj

        if key in self.metadata:
            return self.metadata[key]

        raise KeyError(f"Context key '{key}' not found.")


@dataclass
class QuantumCapabilities:
    input_format: str
    output_format: str
