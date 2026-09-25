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


def parse_extra_args(args: List[str]) -> dict:
    """
    Parses unkown arbitrary extra CLI options flags into a clean Python dictionary.
    Handles both '--key=value' and '--key value' parameter syntaxes.
    """
    extra_dict = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            # Case A: Syntax option is '--key=value'
            if "=" in arg:
                key, val = arg.split("=", 1)
                extra_dict[key.lstrip("-")] = val
                i += 1
            # Case B: Syntax option is '--key value'
            else:
                key = arg.lstrip("-")
                if i + 1 < len(args) and not args[i + 1].startswith("-"):
                    extra_dict[key] = args[i + 1]
                    i += 2
                else:
                    # Fallback flag default value if standalone
                    extra_dict[key] = "True"
                    i += 1
        else:
            # Skip invalid positions or unformatted extra strings
            i += 1
    return extra_dict
