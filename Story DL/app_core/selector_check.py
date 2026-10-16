"""Kiểm tra "sức khoẻ" selector của từng site (thuần BeautifulSoup — không cần GUI/selenium, dễ test).

Cách dùng (xem nút "🩺 Kiểm tra selector" ở tab Activity Logs): dán 1 URL trang thể loại hoặc trang
truyện vào ô URL, app tải HTML bằng ``requests`` rồi đếm số phần tử khớp từng selector trong
``selectors.json`` (đã gộp với mặc định) và thử chạy bộ phân tích danh sách truyện.

Giới hạn: chỉ thấy HTML tĩnh. Site nạp nội dung bằng JavaScript (khosach.mnd.vn) hoặc bị Cloudflare
chặn ``requests`` (monkeydd, trichtinhlau) sẽ được báo rõ thay vì báo sai.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app_core.net_utils import is_cloudflare_challenge

#: (chuỗi có trong host, khoá site trong selectors.json)
_SITE_HOSTS: Tuple[Tuple[str, str], ...] = (
    ("dtv-ebook.com.vn", "dtv"),
    ("monkeydd.com", "monkeyd"),
    ("monkeyd.net.vn", "monkeyd"),
    ("trichtinhlau.com", "trichtinhlau"),
    ("truyenfull", "truyenfull"),
    ("docln.", "hako"),
    ("ln.hako.vn", "hako"),
    ("khosach.mnd.vn", "khosachmnd"),
    ("metruyenchu.com", "metruyenchu"),
    ("metruyencv.com", "metruyenchu"),
    ("tangthuvien.vn", "tangthuvien"),
)

#: Khoá selector áp dụng cho TRANG DANH SÁCH (thể loại); các khoá còn lại là trang truyện/chương.
LIST_PAGE_KEYS = frozenset({
    "genre_book_links", "book_links", "book_container", "book_item", "genre_container", "story_container",
    "story_container_fallback",
})
#: Site cần JavaScript để có nội dung -> HTML tĩnh không phản ánh selector.
JS_RENDERED_SITES = frozenset({"khosachmnd"})


def detect_site(url: str) -> Optional[str]:
    """Khoá site (``"dtv"``, ``"monkeyd"``...) theo host của ``url``; ``None`` nếu chưa hỗ trợ."""
    host = (urlsplit((url or "").strip()).hostname or "").lower()
    for needle, site in _SITE_HOSTS:
        if needle in host:
            return site
    return None


def flatten_selectors(site_cfg: Dict[str, Any]) -> List[Tuple[str, str]]:
    """``[(khoá, selector)]`` — mỗi phần tử của danh sách selector là 1 mục riêng.

    Bỏ qua giá trị không phải selector: số (timeout), ``regex::...``, và các khoá ``*_text`` (chữ cần tìm).
    """
    out: List[Tuple[str, str]] = []
    for key, value in (site_cfg or {}).items():
        if key.endswith("_text"):
            continue
        values = value if isinstance(value, (list, tuple)) else [value]
        for v in values:
            if isinstance(v, str) and v.strip() and not v.startswith("regex::"):
                out.append((key, v.strip()))
    return out


def count_matches(soup: BeautifulSoup, selector: str) -> Optional[int]:
    """Số phần tử khớp ``selector``; ``None`` nếu selector sai cú pháp."""
    try:
        return len(soup.select(selector))
    except Exception:  # noqa: BLE001 - soupsieve ném nhiều loại lỗi cú pháp
        return None


def parse_list_count(site: str, html: str, url: str, selectors: Dict[str, Any]) -> Optional[int]:
    """Số truyện mà bộ phân tích danh sách THẬT của app lấy được từ ``html``; ``None`` nếu site không có."""
    from app_core.constants import BASE_URL
    from app_core import genre_parsers as gp

    cfg = selectors.get(site) or {}
    if site == "dtv":
        return len(gp.parse_dtv_genre(html, url, BASE_URL))
    if site == "trichtinhlau":
        sels = cfg.get("book_links")
        return len(gp.parse_trichtinhlau_genre(html, url, sels or None))
    if site == "monkeyd":
        return len(gp.parse_monkeyd_genre(html, url, cfg.get("story_container") or ""))
    if site == "truyenfull":
        return len(gp.parse_truyenfull_genre(html, url))
    if site == "metruyenchu":
        return len(gp.parse_catalog_genre(html, url, gp.METRUYENCHU_STORY_RE, cfg.get("genre_book_links") or None))
    if site == "tangthuvien":
        return len(gp.parse_catalog_genre(html, url, gp.TANGTHUVIEN_STORY_RE, cfg.get("genre_book_links") or None))
    return None


def build_report(url: str, site: str, html: str, status_code: int, selectors: Dict[str, Any]) -> List[str]:
    """Các dòng báo cáo (để ghi vào Activity Logs)."""
    lines = [f"🩺 Kiểm tra selector — site '{site}' — {url}"]
    if status_code != 200:
        lines.append(f"   ❌ HTTP {status_code} — không đọc được trang (sai URL, bị chặn hoặc site đang lỗi).")
        return lines
    if is_cloudflare_challenge(status_code, html):
        lines.append("   ⚠️ Trang bị Cloudflare chặn khi tải bằng requests — không kiểm tra được từ đây.")
        lines.append("      Hãy chạy thử thật (trình duyệt sẽ xử lý Cloudflare) và xem log lúc quét trang.")
        return lines
    if site in JS_RENDERED_SITES:
        lines.append("   ⚠️ Site nạp nội dung bằng JavaScript/API nên HTML tĩnh không phản ánh selector — "
                     "không kiểm tra được từ đây.")
        return lines

    soup = BeautifulSoup(html or "", "html.parser")
    lines.append(f"   HTML tải được: {len(html or ''):,} ký tự")
    zero_list = zero_other = bad = 0
    for key, sel in flatten_selectors(selectors.get(site) or {}):
        kind = "trang danh sách" if key in LIST_PAGE_KEYS else "trang truyện/chương"
        n = count_matches(soup, sel)
        if n is None:
            bad += 1
            lines.append(f"   ❌ {key} [{kind}]: selector sai cú pháp → {sel}")
        elif n == 0:
            zero_list += key in LIST_PAGE_KEYS
            zero_other += key not in LIST_PAGE_KEYS
            lines.append(f"   ⚪ {key} [{kind}]: 0 khớp → {sel}")
        else:
            lines.append(f"   ✅ {key} [{kind}]: {n} khớp → {sel}")

    try:
        found = parse_list_count(site, html, url, selectors)
    except Exception as exc:  # noqa: BLE001
        found = None
        lines.append(f"   ❌ Bộ phân tích danh sách lỗi: {type(exc).__name__}: {str(exc)[:80]}")
    if found is not None:
        lines.append(f"   🧪 Bộ phân tích danh sách lấy được {found} truyện từ trang này.")

    lines.append("   ℹ️ ⚪ 0 khớp là bình thường nếu khoá đó thuộc loại trang khác với URL bạn dán "
                 "(vd. dán trang thể loại thì khoá 'trang truyện/chương' sẽ là 0).")
    if bad:
        lines.append(f"   ❗ {bad} selector sai cú pháp — sửa trong selectors.json.")
    return lines
