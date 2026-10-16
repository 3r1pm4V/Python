"""Chạy từ thư mục gốc: python -m pytest -q tests/test_wattpad_filters.py"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from app_core.text_utils import (
    compact_tag, extract_wattpad_story_ids, find_blocked_tag, has_required_tag, is_completed_label,
    parse_required_tags, parse_wattpad_list_url, parse_wattpad_story_page, parse_wattpad_tag_slug,
)


@pytest.mark.parametrize("tag", [
    "dammy", "dam my", "Đam Mỹ", "đammỹ", "bl", "BL", "boy love", "boylove", "boys love",
    "dm", "danmei", "yaoi", "dammyhiendai", "#đammỹ", "huynhde", "huynh de", "Huynh Đệ", "#huynhđệ", "huynhdehiendai",
])
def test_blocked_tags_are_detected(tag: str) -> None:
    assert find_blocked_tag(["hvan", tag]) == tag


@pytest.mark.parametrize("tag", ["hvan", "blood", "problem", "fable", "đầm", "dmv", "hiệnđại", "cao h", ""])
def test_normal_tags_are_not_blocked(tag: str) -> None:
    assert find_blocked_tag([tag]) is None


def test_compact_tag_unifies_variants() -> None:
    assert {compact_tag(x) for x in ("Đam Mỹ", "đammỹ", "dam-my", "#DamMy")} == {"dammy"}


@pytest.mark.parametrize("text,expected", [
    ("Hoàn Thành", True), ("hoàn thành", True), ("Completed", True),
    ("Chưa hoàn thành", False), ("Incomplete", False), ("Not completed", False),
    ("Đang ra", False), ("", False),
])
def test_is_completed_label(text: str, expected: bool) -> None:
    assert is_completed_label(text) is expected


_PAGE = """
<div class="x"><div class="GZxny">Hoàn Thành</div><div class="GZxny">12 chương</div></div>
<div class="uHKL3"><a>#hvan</a><a>cao h</a><a>đammỹ</a></div>
"""


def test_parse_story_page_with_user_selectors() -> None:
    done, tags = parse_wattpad_story_page(_PAGE, "div.GZxny:nth-child(1)", ".uHKL3")
    assert done is True and tags == ["hvan", "cao h", "đammỹ"]
    assert find_blocked_tag(tags) == "đammỹ"


def test_parse_story_page_unknown_status_is_none() -> None:
    done, tags = parse_wattpad_story_page("<p>trống</p>", "div.GZxny:nth-child(1)", ".uHKL3")
    assert done is None and tags == []
    done, _ = parse_wattpad_story_page(_PAGE.replace("Hoàn Thành", "Đang ra"), "div.GZxny:nth-child(1)", ".uHKL3")
    assert done is False


def test_extract_story_ids_dedupes_and_keeps_order() -> None:
    html = '<a href="/story/11-a">x</a><a href="/story/22-b">y</a><a href="/story/11-a">z</a>'
    assert extract_wattpad_story_ids(html) == ["11", "22"]
    assert extract_wattpad_story_ids("") == []


@pytest.mark.parametrize("url,expected", [
    ("https://www.wattpad.com/stories/hvan", "hvan"),
    ("https://www.wattpad.com/stories/%C4%91amm%E1%BB%B9/", "đammỹ"),
    ("https://www.wattpad.com/story/123-abc", None),
    ("https://evil.com/stories/hvan", None),
    ("ftp://www.wattpad.com/stories/hvan", None),
    ("", None),
])
def test_parse_tag_slug(url: str, expected: Optional[str]) -> None:
    assert parse_wattpad_tag_slug(url) == expected


# --- Bộ lọc tổng hợp trong WattpadMixin (bỏ qua nếu không có customtkinter) -------------------
def _make_mixin(completed_only: bool, page: Optional[tuple] = None) -> Any:
    pytest.importorskip("customtkinter")
    from scrapers.wattpad import WattpadMixin

    class Stub(WattpadMixin):
        completed_only_var = SimpleNamespace(get=lambda: completed_only)
        logs: List[str] = []

        def log(self, msg: str) -> None:
            self.logs.append(msg)

        def _wattpad_fetch_story_page(self, session: Any, story_id: str):  # không gọi mạng
            return page if page is not None else (None, [])

    return Stub()


def _meta(**kw: Any) -> Dict[str, Any]:
    return {"completed": True, "tags": ["hvan", "ngontinh"], **kw}


def test_filter_passes_clean_completed_story() -> None:
    assert _make_mixin(True)._wattpad_filter_reason(None, "1", _meta()) is None


def test_filter_blocks_dam_my_even_when_completed() -> None:
    reason = _make_mixin(True)._wattpad_filter_reason(None, "1", _meta(tags=["hvan", "đammỹ"]))
    assert reason and "Đam mỹ" in reason


def test_filter_completed_only_toggle() -> None:
    assert "Hoàn Thành" in (_make_mixin(True)._wattpad_filter_reason(None, "1", _meta(completed=False)) or "")
    assert _make_mixin(False)._wattpad_filter_reason(None, "1", _meta(completed=False)) is None


def test_filter_falls_back_to_page_selectors_when_api_lacks_data() -> None:
    m = _make_mixin(True, page=(True, ["hvan", "boylove"]))
    reason = m._wattpad_filter_reason(None, "1", {"tags": []})
    assert reason and "boylove" in reason
    m = _make_mixin(True, page=(None, ["hvan"]))
    assert "không xác định" in (m._wattpad_filter_reason(None, "1", {"tags": ["hvan"]}) or "")


def test_parse_required_tags() -> None:
    assert parse_required_tags("hvan, caoh;#hvan\n cao h ") == ["hvan", "caoh", "cao h"]
    assert parse_required_tags("") == [] and parse_required_tags(" , ; ") == []


def test_has_required_tag_any_of_and_compact_match() -> None:
    assert has_required_tag(["Ngôn tình", "cao h"], ["hvan", "caoh"]) is True   # "cao h" == "caoh"
    assert has_required_tag(["hvan"], ["hvan"]) is True
    assert has_required_tag(["romance", "hvanx"], ["hvan"]) is False            # không khớp chuỗi con
    assert has_required_tag([], ["hvan"]) is False
    assert has_required_tag(["bất kỳ"], []) is True                              # không ràng buộc


def test_filter_requires_tag_before_other_checks() -> None:
    m = _make_mixin(False)
    reason = m._wattpad_filter_reason(None, "1", _meta(tags=["romance", "fantasy"]), ["hvan", "caoh"])
    assert reason and "tag bắt buộc" in reason and m._wattpad_last_skip_kind == "tag_mismatch"
    assert m._wattpad_filter_reason(None, "1", _meta(tags=["romance", "caoh"]), ["hvan", "caoh"]) is None
    # có tag bắt buộc nhưng vẫn là đam mỹ -> vẫn bị loại
    r = m._wattpad_filter_reason(None, "1", _meta(tags=["hvan", "dammy"]), ["hvan"])
    assert r and "Đam mỹ" in r


@pytest.mark.parametrize("url,expected", [
    ("https://www.wattpad.com/search/hvan", ("search", "hvan")),
    ("https://www.wattpad.com/search/cao%20h/", ("search", "cao h")),
    ("https://www.wattpad.com/stories/hvan", ("tag", "hvan")),
    ("https://www.wattpad.com/search/", None),
    ("https://www.wattpad.com/search/a/b", None),
    ("https://evil.com/search/hvan", None),
    ("https://www.wattpad.com/story/123-abc", None),
])
def test_parse_list_url(url: str, expected: Optional[tuple]) -> None:
    assert parse_wattpad_list_url(url) == expected
