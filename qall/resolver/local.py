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
import os
import platform

from qall.object import Resource, ResourceAvailability, CpuSpec


def get_local_resource() -> Resource:
    """
    Returns a placeholder Resource representing the user's local host machine.
    """
    cores = os.cpu_count() or 4
    processor_name = platform.processor() or "local-cpu"

    return Resource(
        name="localhost",
        provider="local",
        availability=ResourceAvailability.available,
        cpu=CpuSpec(
            model_name=processor_name,
            available_cores=cores,
            available_memory_gb=16,
        ),
        gpu=None,
        price=None,
    )
