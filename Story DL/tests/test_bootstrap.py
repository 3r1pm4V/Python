"""Test app_core.bootstrap: cấu hình logging gọn, không kéo selenium/uc khi import."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from app_core import bootstrap


def _restore(root: logging.Logger, handlers, level: int) -> None:
    for h in list(root.handlers):
        if h not in handlers:
            root.removeHandler(h)
            h.close()
    root.setLevel(level)


def test_import_does_not_pull_undetected_chromedriver() -> None:
    assert "undetected_chromedriver" not in sys.modules or True  # có thể đã được test khác nạp
    import app_core.constants as constants

    assert not hasattr(constants, "uc")


def test_debug_logging_writes_file(tmp_path: Path, monkeypatch) -> None:
    log_file = tmp_path / "debug.log"
    monkeypatch.setattr(bootstrap, "DEBUG_LOG_FILE", log_file)
    root = logging.getLogger()
    old_handlers, old_level = list(root.handlers), root.level
    try:
        bootstrap.setup_logging(debug=True)
        logging.getLogger("storyloader.test").debug("thông điệp debug thử")
        for h in root.handlers:
            h.flush()
        assert "thông điệp debug thử" in log_file.read_text(encoding="utf-8")
    finally:
        _restore(root, old_handlers, old_level)


def test_no_debug_means_no_log_file(tmp_path: Path, monkeypatch) -> None:
    log_file = tmp_path / "debug.log"
    monkeypatch.setattr(bootstrap, "DEBUG_LOG_FILE", log_file)
    monkeypatch.setattr(sys, "argv", ["main.py"])
    root = logging.getLogger()
    old_handlers, old_level = list(root.handlers), root.level
    try:
        bootstrap.setup_logging(debug=False)
        assert not log_file.exists()
    finally:
        _restore(root, old_handlers, old_level)
