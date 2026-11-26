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

from qall.core.quantum_run import execute_quantum_sample, execute_quantum_estimation


def sample(target: Any, *args, **kwargs):
    shots = args[0] if args else kwargs.pop("shots", 0)
    kwargs.pop("autosleep_after", None)

    return execute_quantum_sample(target, shots, **kwargs)


def observe(target: Any, *args, **kwargs):
    raise NotImplementedError(
        "The `observe` function is not implemented in this version"
    )
