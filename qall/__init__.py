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

import logging
import os

formatter = logging.Formatter(
    fmt="[%(asctime)s] %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger = logging.getLogger(__name__)
logger.addHandler(console_handler)

# Optional: Prevent logs from propagating to the global root logger
# to avoid duplicate logs if the end-user also configures logging.
logger.propagate = False


def _resolve_logging_level() -> int:
    """Resolve qall's base logging level from the ``QALL_LOGGING_LEVEL`` env var.

    Unknown values fall back to :data:`logging.INFO` so plain ``qall`` usage keeps
    its current behavior.
    """
    raw = os.getenv("QALL_LOGGING_LEVEL")
    if not raw:
        return logging.INFO
    try:
        return logging.getLevelNamesMapping()[raw.upper()]
    except KeyError:
        return logging.INFO


# The qall logger tracks QALL_LOGGING_LEVEL (default INFO). This makes a
# "qall debug mode" reachable through the documented env knob, and gates the
# verbosity of third-party loggers routed below (see _configure_pyan_logging).
logger.setLevel(_resolve_logging_level())


# Attach qall's console handler to third-party loggers (e.g. pyan3) under this
# label so repeated configuration calls never duplicate the handler.
_QALL_CONSOLE_HANDLER_NAME = "qall-console"


def _configure_pyan_logging() -> None:
    """Route pyan3's log records through qall's handler and gate its verbosity.

    pyan's loggers (``pyan``, ``pyan.analyzer``, ``pyan.cyc``, ...) normally
    propagate to the root logger, so qall's CLI ``logging.basicConfig(level=INFO)``
    used to dump every pyan INFO/DEBUG record raw to stderr, as a wall of text
    outside qall's output format. This:
      - stops the ``pyan`` logger from propagating to the root logger;
      - attaches qall's console handler (with qall's formatter) to it, so pyan
        output shares qall's ``[...] LEVEL | name | message`` format;
      - gates pyan's priority behind qall's: INFO/DEBUG only when qall itself runs
        at DEBUG, otherwise WARNING+ (real pyan warnings/errors still surface).

    Idempotent, so it is safe to call both from this module's import and from the
    CLI logging bootstrap.
    """
    pyan_logger = logging.getLogger("pyan")
    if not any(
        getattr(handler, "name", None) == _QALL_CONSOLE_HANDLER_NAME
        for handler in pyan_logger.handlers
    ):
        shared = logging.StreamHandler()
        shared.setFormatter(formatter)
        shared.set_name(_QALL_CONSOLE_HANDLER_NAME)
        pyan_logger.addHandler(shared)
    pyan_logger.propagate = False
    pyan_logger.setLevel(
        logging.DEBUG
        if logger.getEffectiveLevel() <= logging.DEBUG
        else logging.WARNING
    )


_configure_pyan_logging()

from qall.sdk import task, workflow, run

__all__ = ["task", "workflow", "run"]
