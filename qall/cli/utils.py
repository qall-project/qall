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
from typing import List


def parse_extra_args(args: list[str]) -> dict[str, str]:
    """
    Parse les arguments supplémentaires de la CLI.
    Exemple: ['--project-id=123', '--secret-key', 'abc'] -> {'project_id': '123', 'secret_key': 'abc'}
    """
    creds = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            key_val = arg[2:].split("=", 1)
            key = key_val[0].replace(
                "-", "_"
            )  # Normalisation: project-id -> project_id

            if len(key_val) > 1:
                creds[key] = key_val[1]
            elif i + 1 < len(args) and not args[i + 1].startswith("-"):
                creds[key] = args[i + 1]
                i += 1
            else:
                creds[key] = "true"
        i += 1
    return creds
