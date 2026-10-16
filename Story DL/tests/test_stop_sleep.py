"""Test _sleep ngắt được bằng STOP (OrchestratorMixin; cần selenium + bs4, tự bỏ qua nếu thiếu)."""
from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("selenium")
pytest.importorskip("bs4")

from app_core.orchestrator_mixin import OrchestratorMixin  # noqa: E402


class Dummy(OrchestratorMixin):
    def __init__(self, running: bool) -> None:
        self._stop_event = threading.Event()
        if not running:
            self._stop_event.set()


def test_sleep_completes_when_running() -> None:
    d = Dummy(running=True)
    t0 = time.monotonic()
    assert d._sleep(0.05) is True
    assert time.monotonic() - t0 >= 0.04


def test_sleep_random_range_completes() -> None:
    assert Dummy(running=True)._sleep(0.01, 0.03) is True


def test_sleep_returns_immediately_when_stopped() -> None:
    d = Dummy(running=False)
    t0 = time.monotonic()
    assert d._sleep(5) is False
    assert time.monotonic() - t0 < 1


def test_stop_during_sleep_wakes_up_early() -> None:
    d = Dummy(running=True)
    timer = threading.Timer(0.05, d._stop_event.set)
    timer.start()
    t0 = time.monotonic()
    assert d._sleep(5) is False
    timer.join()
    assert time.monotonic() - t0 < 2


def test_negative_sleep_is_safe() -> None:
    assert Dummy(running=True)._sleep(-1) is True
