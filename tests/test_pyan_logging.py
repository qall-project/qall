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

"""
Guardrail for the pyan3 logging contract (see ``qall/_configure_pyan_logging``).

pyan's loggers must be routed through qall's own handler (so its output shares
qall's ``[...] LEVEL | name | message`` format) and their verbosity must be
gated behind qall's: INFO/DEBUG only when qall itself runs at DEBUG, otherwise
WARNING+. It also pins that the ``QALL_LOGGING_LEVEL`` env knob really lowers
the ``qall`` logger level (the gate depends on it).
"""

import logging
import tempfile
from pathlib import Path

import pytest

from qall import (
    _configure_pyan_logging,
    _resolve_logging_level,
    logger as qall_logger,
)
from qall.specification.utils import _build_call_graph_from_sources


class _RecordCapture(logging.Handler):
    """Test handler collecting every record routed to it."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture()
def pyan_capture():
    """Attach a capture handler to the ``pyan`` logger and restore its state."""
    pyan_logger = logging.getLogger("pyan")
    capture = _RecordCapture()
    prev_level = pyan_logger.level
    pyan_logger.addHandler(capture)
    try:
        yield capture
    finally:
        pyan_logger.removeHandler(capture)
        pyan_logger.setLevel(prev_level)
        _configure_pyan_logging()


@pytest.fixture()
def restore_qall_level():
    """Snapshot/restore the ``qall`` logger level (and the pyan gate) around a test."""
    prev_level = qall_logger.level
    yield
    qall_logger.setLevel(prev_level)
    _configure_pyan_logging()


def _qall_console_handler():
    """The formatter-carrying handler qall attaches to the pyan logger."""
    for handler in logging.getLogger("pyan").handlers:
        if getattr(handler, "name", None) == "qall-console":
            return handler
    raise AssertionError("qall-console handler not attached to the pyan logger")


def test_resolve_logging_level_is_env_driven(monkeypatch):
    monkeypatch.delenv("QALL_LOGGING_LEVEL", raising=False)
    assert _resolve_logging_level() == logging.INFO

    monkeypatch.setenv("QALL_LOGGING_LEVEL", "debug")
    assert _resolve_logging_level() == logging.DEBUG

    monkeypatch.setenv("QALL_LOGGING_LEVEL", "WARNING")
    assert _resolve_logging_level() == logging.WARNING

    # Unknown values must not crash the CLI.
    monkeypatch.setenv("QALL_LOGGING_LEVEL", "banana")
    assert _resolve_logging_level() == logging.INFO


def test_pyan_configured_idempotently():
    _configure_pyan_logging()
    _configure_pyan_logging()
    shared = [
        h
        for h in logging.getLogger("pyan").handlers
        if getattr(h, "name", None) == "qall-console"
    ]
    assert len(shared) == 1


def test_pyan_gated_to_warning_at_default_qall_level(
    restore_qall_level, pyan_capture
):
    qall_logger.setLevel(logging.INFO)
    _configure_pyan_logging()

    pyan_logger = logging.getLogger("pyan")
    assert pyan_logger.level == logging.WARNING
    assert pyan_logger.propagate is False  # no raw root/basicConfig leak

    pyan_logger.debug("noise")
    pyan_logger.info("chatter")
    pyan_logger.warning("real warning")
    pyan_logger.error("real error")

    # INFO/DEBUG chatter is dropped; WARNING+ still surfaces.
    assert [r.levelno for r in pyan_capture.records] == [
        logging.WARNING,
        logging.ERROR,
    ]
    # Output uses qall's format, not basicConfig's.
    formatted = _qall_console_handler().format(pyan_capture.records[0])
    assert formatted.startswith("[")
    assert "WARNING | pyan | real warning" in formatted


def test_pyan_debug_enabled_when_qall_debug(restore_qall_level, pyan_capture):
    qall_logger.setLevel(logging.DEBUG)
    _configure_pyan_logging()

    pyan_logger = logging.getLogger("pyan")
    assert pyan_logger.level == logging.DEBUG

    pyan_logger.debug("noise")
    pyan_logger.info("chatter")

    assert [r.levelno for r in pyan_capture.records] == [
        logging.DEBUG,
        logging.INFO,
    ]
    formatted = _qall_console_handler().format(pyan_capture.records[0])
    assert "DEBUG | pyan | noise" in formatted


def test_call_graph_build_keeps_pyan_quiet_and_unrouted(caplog, restore_qall_level):
    qall_logger.setLevel(logging.INFO)
    _configure_pyan_logging()
    caplog.set_level(logging.DEBUG)  # capture everything that reaches the root

    with tempfile.TemporaryDirectory() as tmpdir:
        file_a = Path(tmpdir) / "a.py"
        file_a.write_text("def f():\n    return g()\n\ndef g():\n    return 1\n")

        nodes, edges = _build_call_graph_from_sources({"a": file_a})

    assert set(nodes) == {"a.f", "a.g"}
    assert {"caller": "a.f", "callee": "a.g"} in edges

    # pyan must not leak to the root logger (which is what produced the raw
    # "text wall" before qall routed and gated it).
    leaked = [
        r
        for r in caplog.records
        if r.name == "pyan" or r.name.startswith("pyan.")
    ]
    assert not leaked
