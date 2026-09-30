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

from typing import Dict, Union

import json
import keyring


def set_token(service_name: str, user: str, credentials: Union[Dict, str]) -> bool:
    try:
        if isinstance(credentials, dict):
            credentials = json.dumps(credentials)

        keyring.set_password(service_name, user, credentials)
        return True
    except Exception as e:
        raise e


def get_token(service_name: str, user: str) -> str | dict | None:
    try:
        credentials = keyring.get_password(service_name, user)
        if credentials is None:
            return None

        try:
            return json.loads(credentials)
        except (json.JSONDecodeError, TypeError):
            return credentials

    except Exception as e:
        raise e


def delete_token(service_name: str, user: str) -> bool:
    try:
        keyring.delete_password(service_name, user)
        return True
    except Exception as e:
        # If the password mapping does not exist, silence it gracefully or return false
        return False
