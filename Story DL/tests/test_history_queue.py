"""Test HistoryQueueMixin: history/queue/blocked (file I/O) và khớp tên file EPUB."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app_core import history_queue_mixin as hq
from app_core.history_queue_mixin import HistoryQueueMixin


class Store(HistoryQueueMixin):
    def __init__(self) -> None:
        self.downloaded_urls = set()
        self.downloaded_filenames = {}
        self.blocked_urls = set()
        self._history_lock = threading.Lock()
        self._queue_lock = threading.Lock()


def _make_store(tmp_path: Path, monkeypatch) -> Store:
    monkeypatch.setattr(hq, "HISTORY_FILE", tmp_path / "history.txt")
    monkeypatch.setattr(hq, "QUEUE_FILE", tmp_path / "queue.txt")
    monkeypatch.setattr(hq, "BLOCKED_FILE", tmp_path / "blocked.txt")
    return Store()


def touch(folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"PK")


# ---------------------------------------------------------------- normalize_url
@pytest.mark.parametrize("raw,expected", [
    ("https://a.vn/truyen/x/", "https://a.vn/truyen/x"),
    ("https://a.vn/truyen/x?page=2", "https://a.vn/truyen/x"),
    ("https://a.vn/x.html", "https://a.vn/x.html"),
    ("", ""),
])
def test_normalize_url(raw: str, expected: str) -> None:
    assert Store().normalize_url(raw) == expected


# ---------------------------------------------------------------- history
def test_history_roundtrip_with_filename(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    s.save_history("https://a.vn/x/", "Truyện X - Tác Giả")
    s.save_history("https://a.vn/y")            # không có tên file

    fresh = Store()
    urls = fresh.load_history()
    assert urls == {"https://a.vn/x", "https://a.vn/y"}
    assert fresh.downloaded_filenames == {"https://a.vn/x": "Truyện X - Tác Giả"}


def test_history_does_not_duplicate_lines(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    s.save_history("https://a.vn/x", "X")
    s.save_history("https://a.vn/x/?utm=1", "X")
    lines = (tmp_path / "history.txt").read_text(encoding="utf-8").splitlines()
    assert lines == ["https://a.vn/x\tX"]


def test_history_adds_filename_later_in_memory_only(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    s.save_history("https://a.vn/x")
    s.save_history("https://a.vn/x", "Tên Mới")
    assert s.downloaded_filenames["https://a.vn/x"] == "Tên Mới"


def test_load_history_missing_file_is_empty(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    assert s.load_history() == set()


# ---------------------------------------------------------------- queue
def test_queue_add_remove(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    s.queue_add("https://a.vn/1/")
    s.queue_add("https://a.vn/2")
    s.queue_add("https://a.vn/1")               # trùng sau chuẩn hoá -> không thêm
    assert (tmp_path / "queue.txt").read_text(encoding="utf-8").splitlines() == ["https://a.vn/1", "https://a.vn/2"]

    s.queue_remove("https://a.vn/1/")
    assert (tmp_path / "queue.txt").read_text(encoding="utf-8").splitlines() == ["https://a.vn/2"]

    s.queue_remove("https://a.vn/2")
    assert (tmp_path / "queue.txt").read_text(encoding="utf-8") == ""


def test_queue_remove_missing_is_noop(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    s.queue_remove("https://a.vn/none")         # không có file queue -> không lỗi
    s.queue_add("https://a.vn/1")
    s.queue_remove("https://a.vn/none")
    assert (tmp_path / "queue.txt").read_text(encoding="utf-8").splitlines() == ["https://a.vn/1"]


# ---------------------------------------------------------------- blocked
def test_blocked_roundtrip_and_sanitizes_tabs(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    s.save_blocked("https://w.com/story/1", "có\ttag\nBL", "Tên\tcó\ttab")
    s.save_blocked("https://w.com/story/1/", "lần 2")        # trùng -> bỏ qua

    raw = (tmp_path / "blocked.txt").read_text(encoding="utf-8")
    assert raw.count("\n") == 1                                # đúng 1 dòng, không bị TAB/xuống dòng phá
    assert len(raw.rstrip("\n").split("\t")) == 3

    assert Store().load_blocked() == {"https://w.com/story/1"}


# ---------------------------------------------------------------- _name_matches
@pytest.mark.parametrize("file_name,term,truncated,expected", [
    ("đấu phá thương khung.epub", "đấu phá thương khung", False, True),
    ("đấu phá thương khung - thiên tằm.epub", "đấu phá thương khung", False, True),
    ("đấu phá thương khung.epub", "đấu phá", False, False),     # không khớp tiền tố giữa chừng
    ("đấu phá thương khung.epub", "đấu phá", True, True),       # term đã bị cắt -> chỉ so tiền tố
    ("khác hẳn.epub", "đấu phá", False, False),
])
def test_name_matches(file_name: str, term: str, truncated: bool, expected: bool) -> None:
    assert HistoryQueueMixin._name_matches(file_name, term, truncated) is expected


# ---------------------------------------------------------------- check_epub_exists
@pytest.mark.parametrize("use_cache", [False, True])
def test_check_epub_exists_exact_and_author_suffix(tmp_path: Path, monkeypatch, use_cache: bool) -> None:
    s = _make_store(tmp_path, monkeypatch)
    touch(tmp_path / "out", "Đấu Phá Thương Khung - Thiên Tằm Thổ Đậu.epub")
    cache = {f.name.lower() for f in (tmp_path / "out").rglob("*.epub")} if use_cache else None
    assert s.check_epub_exists(tmp_path / "out", "Đấu Phá Thương Khung", cache=cache)
    assert not s.check_epub_exists(tmp_path / "out", "Đấu Phá", cache=cache)      # 'Đấu Phá' ≠ 'Đấu Phá Thương Khung'
    assert not s.check_epub_exists(tmp_path / "out", "Truyện Khác Hẳn", cache=cache)


@pytest.mark.parametrize("use_cache", [False, True])
def test_check_epub_exists_matches_underscore_variant(tmp_path: Path, monkeypatch, use_cache: bool) -> None:
    """File do app tạo thay ký tự cấm bằng '_' nhưng tên 'sạch' bỏ hẳn ký tự đó: phải khớp cả hai."""
    s = _make_store(tmp_path, monkeypatch)
    touch(tmp_path / "out", "Tên_ Truyện - Tác Giả.epub")
    cache = {f.name.lower() for f in (tmp_path / "out").rglob("*.epub")} if use_cache else None
    assert s.check_epub_exists(tmp_path / "out", "Tên: Truyện", cache=cache)


def test_check_epub_exists_searches_subfolders(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    touch(tmp_path / "out" / "tiên hiệp", "Phàm Nhân Tu Tiên.epub")
    assert s.check_epub_exists(tmp_path / "out", "Phàm Nhân Tu Tiên")


def test_check_epub_exists_missing_dir_is_false(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    assert not s.check_epub_exists(tmp_path / "không-có", "Bất Kỳ Truyện Nào")


def test_check_epub_exists_ignores_too_short_names(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    touch(tmp_path / "out", "abcd efgh.epub")
    assert not s.check_epub_exists(tmp_path / "out", "abc")      # tên <5 ký tự không được khớp mờ


# ---------------------------------------------------------------- is_story_already_downloaded
def test_already_downloaded_uses_history_filename_when_file_exists(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    out = tmp_path / "out"
    touch(out, "Tên Thật Trên Đĩa.epub")
    s.save_history("https://a.vn/x", "Tên Thật Trên Đĩa")
    assert s.is_story_already_downloaded("https://a.vn/x/", out, "tiêu đề khác")


def test_history_entry_without_file_means_not_downloaded(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    s.save_history("https://a.vn/x", "Đã Bị Xoá")
    assert not s.is_story_already_downloaded("https://a.vn/x", out, "Đã Bị Xoá")


def test_file_on_disk_without_history_is_recorded(tmp_path: Path, monkeypatch) -> None:
    s = _make_store(tmp_path, monkeypatch)
    out = tmp_path / "out"
    touch(out, "Truyện Có Sẵn.epub")
    assert s.is_story_already_downloaded("https://a.vn/new", out, "Truyện Có Sẵn")
    assert "https://a.vn/new" in s.downloaded_urls                  # tự bổ sung vào lịch sử
