"""Chạy từ thư mục gốc: python -m pytest -q tests"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import List, Union

import pytest

from app_core.net_utils import get_with_retry, is_valid_epub


class FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, script: List[Union[FakeResp, Exception]]) -> None:
        self.script = list(script)
        self.calls = 0

    def get(self, url: str, **_kw: object) -> FakeResp:
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _run(script: List[Union[FakeResp, Exception]], **kw: object):
    sleeps: List[float] = []
    sess = FakeSession(script)
    return sess, sleeps, lambda: get_with_retry(sess, "u", sleep=sleeps.append, **kw)


def test_returns_last_response_instead_of_runtimeerror() -> None:
    last = FakeResp(503)
    sess, sleeps, call = _run([FakeResp(503), last], attempts=2)
    assert call() is last          # bản cũ: RuntimeError("No attempts made")
    assert len(sleeps) == 1        # không sleep sau lần thử cuối
    assert sess.calls == 2


def test_retries_then_succeeds_and_closes_failed_response() -> None:
    bad, ok = FakeResp(429), FakeResp(200)
    _, _, call = _run([bad, ok], attempts=3)
    assert call() is ok
    assert bad.closed


def test_raises_last_network_error() -> None:
    _, _, call = _run([OSError("a"), OSError("b")], attempts=2)
    with pytest.raises(OSError, match="b"):
        call()


def test_invalid_attempts() -> None:
    with pytest.raises(ValueError):
        get_with_retry(FakeSession([]), "u", attempts=0)


def test_is_valid_epub(tmp_path: Path) -> None:
    good, html, empty = (tmp_path / n for n in ("g.epub", "h.epub", "e.epub"))
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
    html.write_text("<html>quota exceeded</html>", encoding="utf-8")
    empty.touch()
    assert is_valid_epub(good)
    assert not is_valid_epub(html)
    assert not is_valid_epub(empty)
    assert not is_valid_epub(tmp_path / "missing.epub")
