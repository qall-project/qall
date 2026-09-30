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

from qall.core.quantum_run import create_quantum_run


def run(target: Any, shots: int = 0, autosleep_after: str = None, **kwargs):
    if isinstance(target, str):  # case external workflow
        raise NotImplementedError

    if callable(target):  # case other task
        raise NotImplementedError

    return create_quantum_run(target, shots, **kwargs)  # case quantum circuit
