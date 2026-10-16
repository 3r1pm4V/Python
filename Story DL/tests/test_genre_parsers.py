"""Chạy từ thư mục gốc: python -m pytest -q tests"""
from __future__ import annotations

from app_core.genre_parsers import (
    parse_dtv_genre, parse_monkeyd_genre, parse_trichtinhlau_genre,
    parse_truyenfull_genre, parse_catalog_genre,
    METRUYENCHU_STORY_RE, TANGTHUVIEN_STORY_RE, is_monkeyd_story_url,
)
from app_core.net_utils import (
    build_genre_page_url, is_cloudflare_challenge, normalize_proxy, proxy_for_url,
    requests_proxies, chrome_proxy_arg,
)


def test_cloudflare_cdn_reference_is_not_a_challenge() -> None:
    page = '<html><script src="https://cdnjs.cloudflare.com/x.js"></script>' + "x" * 2000
    assert not is_cloudflare_challenge(200, page)
    assert not is_cloudflare_challenge(200, '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js">')


def test_cloudflare_real_challenge_detected() -> None:
    assert is_cloudflare_challenge(403, "<html><title>Just a moment...</title>")
    assert is_cloudflare_challenge(503, "error code: Cloudflare")


def test_page_url_builder() -> None:
    assert build_genre_page_url("https://truyenfull.vn/the-loai/tien-hiep/", 1) == "https://truyenfull.vn/the-loai/tien-hiep"
    assert build_genre_page_url("https://truyenfull.vn/the-loai/tien-hiep/trang-3/", 2) == "https://truyenfull.vn/the-loai/tien-hiep/trang-2/"
    assert build_genre_page_url("https://monkeydd.com/the-loai/x?page=5", 2) == "https://monkeydd.com/the-loai/x?page=2"
    assert build_genre_page_url("https://www.monkeydd.com/the-loai/x", 3) == "https://monkeydd.com/the-loai/x?page=3"
    assert build_genre_page_url("https://tangthuvien.vn/tong-hop?ctg=1", 2) == "https://tangthuvien.vn/tong-hop?ctg=1&page=2"
    assert build_genre_page_url("https://dtv-ebook.com.vn/the-loai/a.html", 4) == "https://dtv-ebook.com.vn/the-loai/a/4.html"
    assert build_genre_page_url("https://dtv-ebook.com.vn/khoa-hoc-tam-ly-hoc-1470.html", 1) == "https://dtv-ebook.com.vn/khoa-hoc-tam-ly-hoc-1470.html"
    assert build_genre_page_url("https://dtv-ebook.com.vn/khoa-hoc-tam-ly-hoc-1470.html", 2) == "https://dtv-ebook.com.vn/khoa-hoc-tam-ly-hoc-1470/2.html"
    assert build_genre_page_url("https://dtv-ebook.com.vn/khoa-hoc-tam-ly-hoc-1470/1.html", 1) == "https://dtv-ebook.com.vn/khoa-hoc-tam-ly-hoc-1470.html"
    assert build_genre_page_url("https://dtv-ebook.com.vn/the-loai/a/2.html", 3) == "https://dtv-ebook.com.vn/the-loai/a/3.html"


def test_truyenfull_ignores_menu_and_keeps_order() -> None:
    html = """
    <ul class="nav"><li><a href="/the-loai/tien-hiep/">Tiên Hiệp</a></li></ul>
    <div class="list-truyen">
      <div class="row"><h3 class="truyen-title"><a href="/b-truyen/">B Truyện</a></h3></div>
      <div class="row"><h3 class="truyen-title"><a href="/a-truyen/">A Truyện</a></h3></div>
      <div class="row"><h3 class="truyen-title"><a href="/b-truyen/">B Truyện</a></h3></div>
    </div>
    <ul class="pagination"><li><a href="/the-loai/tien-hiep/trang-2/">2</a></li></ul>"""
    items = parse_truyenfull_genre(html, "https://truyenfull.vn/the-loai/tien-hiep/")
    assert [i["title"] for i in items] == ["B Truyện", "A Truyện"]
    assert items[0]["url"] == "https://truyenfull.vn/b-truyen/"


def test_dtv_prefers_text_title_over_empty_cover_anchor() -> None:
    html = """<li class="itemtruyen">
      <a href="/truyen-a_12.html"><img alt="Bìa A"></a>
      <h2 class="tensanpham"><a href="/truyen-a_12.html?x=1">Truyện A</a></h2>
      <a href="/the-loai/kiem-hiep_3.html">Kiếm hiệp</a></li>"""
    items = parse_dtv_genre(html, "https://dtv-ebook.com.vn/the-loai/x/1.html", "https://dtv-ebook.com.vn")
    assert items == [{"url": "https://dtv-ebook.com.vn/truyen-a_12.html", "title": "Truyện A", "author": ""}]


def test_monkeyd_filters_non_story_links() -> None:
    assert is_monkeyd_story_url("https://monkeydd.com/ten-truyen.html")
    assert not is_monkeyd_story_url("https://monkeydd.com/ten-truyen/chuong-1.html")
    assert not is_monkeyd_story_url("https://monkeydd.com/the-loai/x.html")
    html = """<div class="page-content"><a href="/nhom-dich/abc.html">Nhóm</a>
      <a href="/truyen-hay.html" title="Truyện Hay">x</a><a href="/truyen-hay/chuong-2.html">Chương 2</a></div>"""
    items = parse_monkeyd_genre(html, "https://monkeydd.com/the-loai/x")
    assert [(i["url"], i["title"]) for i in items] == [("https://monkeydd.com/truyen-hay.html", "Truyện Hay")]


def test_trichtinhlau_basic() -> None:
    html = '<article class="col-6"><a href="/xem-truyen/abc" title="ABC">ABC</a></article>'
    items = parse_trichtinhlau_genre(html, "https://trichtinhlau.com/the-loai/x")
    assert items[0]["url"] == "https://trichtinhlau.com/xem-truyen/abc"


def test_catalog_excludes_chapters_authors_genres() -> None:
    html = """<h4><a href="/doc-truyen/than-an">Thần Ấn</a></h4>
      <a href="/doc-truyen/than-an/chuong-1">Chương 1</a><a href="/the-loai/tien-hiep">TH</a>
      <a href="/tac-gia/x">X</a><a href="/doc-truyen/khac">Khác</a>"""
    items = parse_catalog_genre(html, "https://tangthuvien.vn/tong-hop", TANGTHUVIEN_STORY_RE)
    assert [i["title"] for i in items] == ["Thần Ấn", "Khác"]
    html2 = '<a href="/truyen/abc">ABC</a><a href="/truyen/abc/chuong-3">c3</a>'
    assert len(parse_catalog_genre(html2, "https://metruyencv.com/truyen", METRUYENCHU_STORY_RE)) == 1


def test_proxy_only_for_trichtinhlau() -> None:
    assert normalize_proxy("127.0.0.1:1080") == "socks5://127.0.0.1:1080"
    assert normalize_proxy("  ") == ""
    assert proxy_for_url("https://trichtinhlau.com/x", "127.0.0.1:1080") == "socks5://127.0.0.1:1080"
    assert proxy_for_url("https://cdn.trichtinhlau.com/a.jpg", "127.0.0.1:1080")
    assert proxy_for_url("https://monkeydd.com/x", "127.0.0.1:1080") == ""
    assert proxy_for_url("https://trichtinhlau.com/x", "") == ""
    assert requests_proxies("https://trichtinhlau.com/x", "socks5://127.0.0.1:1080")["https"] == "socks5h://127.0.0.1:1080"
    assert requests_proxies("https://other.com", "127.0.0.1:1080") is None


def test_chrome_pac_arg() -> None:
    import base64
    arg = chrome_proxy_arg("socks5://127.0.0.1:1080")
    assert arg.startswith("--proxy-pac-url=data:application/x-ns-proxy-autoconfig;base64,")
    pac = base64.b64decode(arg.split("base64,")[1]).decode()
    assert "SOCKS5 127.0.0.1:1080" in pac and "trichtinhlau.com" in pac and 'return "DIRECT"' in pac
    assert chrome_proxy_arg("") == ""
