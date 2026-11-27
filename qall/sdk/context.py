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
from typing import Any

from qall.core.quantum_run import get_quantum_context


class _ContextProxy:
    def __getitem__(self, key: str) -> Any:
        return get_quantum_context()[key]

    def get(self, key: str, default: Any = None) -> Any:
        ctx = get_quantum_context()
        return ctx.get(key, default) if hasattr(ctx, "get") else default

    def __contains__(self, key: str) -> bool:
        ctx = get_quantum_context()
        return key in ctx.bin_metadata or key in ctx.metadata


context = _ContextProxy()
