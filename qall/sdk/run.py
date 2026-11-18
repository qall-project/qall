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
import inspect


def run(target: str, *args, **kwargs):
    ref = target.strip()
    frame = inspect.currentframe()
    caller_globals = frame.f_back.f_globals if frame and frame.f_back else {}
    children_map = caller_globals.get("_QALL_CHILDREN", {})

    if ref not in children_map:
        raise RuntimeError(
            f"External target '{ref}' is not linked in this task's children."
        )
    return children_map[ref](*args, **kwargs)
