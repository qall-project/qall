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
    Parses arbitrary extra CLI option flags into a clean Python dictionary.
    Handles '--key=value', '--key value', and standalone boolean flags.
    Normalizes keys by removing leading dashes and replacing hyphens with underscores.
    
    Example: 
        ['--project-id=123', '--secret-key', 'abc', '--verbose'] 
        -> {'project_id': '123', 'secret_key': 'abc', 'verbose': 'true'}
    """
    extra_dict = {}
    i = 0
    
    while i < len(args):
        arg = args[i]
        
        if arg.startswith("--"):
            # Clean the prefix and prepare the key
            clean_arg = arg.lstrip("-")
            
            if "=" in clean_arg:
                # Case A: Syntax option is '--key=value'
                key, val = clean_arg.split("=", 1)
                extra_dict[key.replace("-", "_")] = val
                i += 1
            else:
                # Case B: Syntax option is '--key value' or standalone flag
                key = clean_arg.replace("-", "_")
                
                # Check if the next argument exists and is a value (not another flag)
                if i + 1 < len(args) and not args[i + 1].startswith("-"):
                    extra_dict[key] = args[i + 1]
                    i += 2
                else:
                    # Fallback flag default value if standalone
                    extra_dict[key] = "true"
                    i += 1
        else:
            # Skip invalid positions or unformatted extra strings
            i += 1
            
    return extra_dict
