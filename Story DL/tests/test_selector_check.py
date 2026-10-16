"""Test app_core.selector_check (thuần BeautifulSoup)."""
from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app_core.constants import DEFAULT_SELECTORS
from app_core.selector_check import (
    build_report, count_matches, detect_site, flatten_selectors, parse_list_count,
)


@pytest.mark.parametrize("url,site", [
    ("https://dtv-ebook.com.vn/co-dai-511.html", "dtv"),
    ("https://www.monkeydd.com/the-loai/ngon-tinh", "monkeyd"),
    ("https://trichtinhlau.com/xem-truyen/abc", "trichtinhlau"),
    ("https://truyenfull.vn/the-loai/tien-hiep/", "truyenfull"),
    ("https://truyenfull.live/x/", "truyenfull"),
    ("https://docln.net/truyen/1-abc", "hako"),
    ("https://ln.hako.vn/truyen/1", "hako"),
    ("https://khosach.mnd.vn/category/new/6019", "khosachmnd"),
    ("https://metruyenchu.com/truyen/abc", "metruyenchu"),
    ("https://tangthuvien.vn/doc-truyen/abc", "tangthuvien"),
    ("https://example.com/", None),
    ("", None),
])
def test_detect_site(url: str, site) -> None:
    assert detect_site(url) == site


def test_flatten_selectors_skips_non_selectors() -> None:
    cfg = {
        "a": "div.x",
        "b": ["p.y", "  ", "span.z"],
        "story_url_pattern": "regex::^https?://x$",
        "epub_tab_text": ["DOWNLOAD", "TẢI VỀ"],
        "timeout": 4,
    }
    assert flatten_selectors(cfg) == [("a", "div.x"), ("b", "p.y"), ("b", "span.z")]
    assert flatten_selectors({}) == []


def test_default_selectors_are_all_valid_css() -> None:
    soup = BeautifulSoup("<html></html>", "html.parser")
    for site, cfg in DEFAULT_SELECTORS.items():
        if not isinstance(cfg, dict):
            continue
        for key, sel in flatten_selectors(cfg):
            assert count_matches(soup, sel) is not None, f"{site}.{key}: selector sai cú pháp: {sel}"


def test_count_matches() -> None:
    soup = BeautifulSoup("<ul><li class='a'>1</li><li class='a'>2</li><li>3</li></ul>", "html.parser")
    assert count_matches(soup, "li.a") == 2
    assert count_matches(soup, "li.zzz") == 0
    assert count_matches(soup, "li[") is None


TRUYENFULL_LIST = """
<div class="list-truyen">
  <div class="row"><h3 class="truyen-title"><a href="/truyen-a/">Truyện A</a></h3></div>
  <div class="row"><h3 class="truyen-title"><a href="/truyen-b/">Truyện B</a></h3></div>
</div>"""


def test_parse_list_count_truyenfull() -> None:
    assert parse_list_count("truyenfull", TRUYENFULL_LIST, "https://truyenfull.vn/the-loai/x/", DEFAULT_SELECTORS) == 2
    assert parse_list_count("hako", TRUYENFULL_LIST, "https://docln.net/x", DEFAULT_SELECTORS) is None


def test_report_happy_path() -> None:
    lines = build_report("https://truyenfull.vn/the-loai/x/", "truyenfull", TRUYENFULL_LIST, 200, DEFAULT_SELECTORS)
    text = "\n".join(lines)
    assert "✅ genre_book_links [trang danh sách]: 2 khớp" in text
    assert "lấy được 2 truyện" in text
    assert "⚪ chapter_content [trang truyện/chương]: 0 khớp" in text


def test_report_marks_broken_selector() -> None:
    sel = {"truyenfull": {"genre_book_links": ["h3 a[", "h3 a"]}}
    text = "\n".join(build_report("https://truyenfull.vn/x/", "truyenfull", TRUYENFULL_LIST, 200, sel))
    assert "❌ genre_book_links" in text and "sai cú pháp" in text
    assert "✅ genre_book_links" in text


def test_report_http_error() -> None:
    lines = build_report("https://truyenfull.vn/x/", "truyenfull", "", 404, DEFAULT_SELECTORS)
    assert len(lines) == 2 and "HTTP 404" in lines[1]


def test_report_cloudflare_challenge() -> None:
    html = "<html><head><title>Just a moment...</title></head><body>_cf_chl_opt</body></html>"
    text = "\n".join(build_report("https://www.monkeydd.com/x", "monkeyd", html, 403, DEFAULT_SELECTORS))
    assert "HTTP 403" in text or "Cloudflare" in text


def test_report_cloudflare_challenge_with_200() -> None:
    html = "<html><head><title>Just a moment...</title></head><body>_cf_chl_opt</body></html>"
    text = "\n".join(build_report("https://www.monkeydd.com/x", "monkeyd", html, 200, DEFAULT_SELECTORS))
    assert "Cloudflare" in text and "khớp" not in text


def test_report_js_rendered_site() -> None:
    text = "\n".join(build_report("https://khosach.mnd.vn/category/new/1", "khosachmnd", "<html></html>", 200, DEFAULT_SELECTORS))
    assert "JavaScript" in text and "khớp" not in text
