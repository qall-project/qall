# Copyright 2026 Scaleway
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
from pathlib import Path

from qall.config.paths import TASK_RUNTIME_WORKDIR

logger = logging.getLogger(__name__)


UNIFIED_FS = TASK_RUNTIME_WORKDIR / "unifs"


def setup_unifs() -> Path:
    """Run this in the parent process before spawning the subprocess"""
    if not UNIFIED_FS.exists():
        logger.info(f"Creating unified FS root directory : {UNIFIED_FS}")
        UNIFIED_FS.mkdir(0o777, parents=True, exist_ok=True)
    return UNIFIED_FS
