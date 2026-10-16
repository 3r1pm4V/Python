"""Bộ phân tích HTML trang DANH SÁCH TRUYỆN (thể loại) — thuần BeautifulSoup, không cần GUI/selenium.

Mỗi hàm nhận HTML + URL trang và trả về ``[{"url", "title", "author"}]`` đã khử trùng lặp,
GIỮ NGUYÊN thứ tự xuất hiện (bản cũ dùng ``list(set(...))`` làm đảo thứ tự ngẫu nhiên).
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

Item = Dict[str, str]

DTV_LINK_SELECTORS = ["li.itemtruyen a", "h2.tensanpham a", "li.itemtruyen h2 a"]
TRICHTINHLAU_LINK_SELECTORS = [
    "article.col-6 a[href*='/xem-truyen/']",
    ".book-info h3 a[href*='/xem-truyen/']",
    "a.book-item-name[href*='/xem-truyen/']",
    ".truyen-item a[href*='/xem-truyen/']",
]
TRUYENFULL_TITLE_SELECTORS = "h3.truyen-title a, h3.title a, .truyen-title a, .title a"
MONKEYD_BLACKLIST = (
    "/the-loai/", "/nhom-dich/", "/chuong-", "/login", "/tao-tai-khoan", "/truyen-moi",
    "/truyen-hoan-thanh", "/truyen-sang-tac", "/danh-sach-nhom-dich", "/tim-kiem",
)


def _anchor_title(a) -> str:
    """Tên truyện của 1 thẻ <a>: thuộc tính title > text > alt của ảnh bên trong."""
    t = (a.get("title") or "").strip()
    if t:
        return t
    text = a.get_text(" ", strip=True)
    if text:
        return text
    img = a.find("img")
    return (img.get("alt") or "").strip() if img else ""


def _title_rank(a) -> int:
    """2 = title/text thật; 1 = chỉ có alt ảnh (thường là 'Bìa ...'); 0 = rỗng."""
    if (a.get("title") or "").strip() or a.get_text(" ", strip=True):
        return 2
    return 1 if _anchor_title(a) else 0


def _add(items: Dict[str, Item], url: str, title: str, author: str = "", rank: int = 2) -> None:
    """Thêm/gộp theo URL: giữ thứ tự lần đầu; chỉ thay title khi nguồn tốt hơn (không so độ dài)."""
    cur = items.get(url)
    if cur is None:
        items[url] = {"url": url, "title": title, "author": author, "_rank": rank}
    elif rank > cur["_rank"]:
        cur["title"], cur["_rank"] = title, rank


def _finish(items: Dict[str, Item]) -> List[Item]:
    out = []
    for it in items.values():
        it = dict(it)
        it.pop("_rank", None)
        out.append(it)
    return out


def _soup(html) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def parse_dtv_genre(html, page_url: str, base_url: str = "") -> List[Item]:
    soup = _soup(html)
    items: Dict[str, Item] = {}
    for sel in DTV_LINK_SELECTORS:
        for a in soup.select(sel):
            href = (a.get("href") or "").strip()
            if not href or not re.search(r"_\d+\.html", href):
                continue
            if "/the-loai/" in href or "/1.html" in href:
                continue
            full = urljoin(base_url or page_url, href.split("?")[0])
            _add(items, full, _anchor_title(a), rank=_title_rank(a))
    return _finish(items)


def parse_trichtinhlau_genre(html, page_url: str, selectors: Optional[Iterable[str]] = None) -> List[Item]:
    soup = _soup(html)
    items: Dict[str, Item] = {}
    for sel in (list(selectors) if selectors else TRICHTINHLAU_LINK_SELECTORS):
        try:
            anchors = soup.select(sel)
        except Exception:
            continue
        for a in anchors:
            href = (a.get("href") or "").strip()
            if href and "/xem-truyen/" in href:
                _add(items, urljoin(page_url, href), _anchor_title(a), rank=_title_rank(a))
    return _finish(items)


def is_monkeyd_story_url(href: str) -> bool:
    """Truyện MonkeyD có dạng https://monkeydd.com/<slug>.html (đúng 1 đoạn path)."""
    if not href or not href.startswith("http") or "monkeydd.com" not in href:
        return False
    if any(x in href for x in MONKEYD_BLACKLIST):
        return False
    path = urlsplit(href).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    return len(parts) == 1 and parts[0].endswith(".html")


def parse_monkeyd_genre(html, page_url: str, container_selector: str = "") -> List[Item]:
    soup = _soup(html)
    items: Dict[str, Item] = {}

    def collect(scope) -> None:
        for a in scope.select("a[href]"):
            full = urljoin(page_url, (a.get("href") or "").strip()).split("?")[0]
            if is_monkeyd_story_url(full):
                _add(items, full, _anchor_title(a), rank=_title_rank(a))

    scopes = []
    for sel in (container_selector, ".page-content"):
        if sel:
            try:
                found = soup.select_one(sel)
            except Exception:
                found = None
            if found is not None:
                scopes.append(found)
    for scope in scopes:
        collect(scope)
        if items:
            break
    if not items:
        collect(soup)
    return _finish(items)


def parse_truyenfull_genre(html, page_url: str) -> List[Item]:
    """Truyện Full: mỗi truyện là 1 ``div.row`` có ``h3.truyen-title > a`` (bản cũ chỉ tìm
    ``.title a`` nên trượt selector, rồi nhặt cả link menu/phân trang qua ``li``)."""
    soup = _soup(html)
    items: Dict[str, Item] = {}
    scope = soup.select_one(".list-truyen") or soup
    for a in scope.select(TRUYENFULL_TITLE_SELECTORS):
        href = (a.get("href") or "").strip()
        title = _anchor_title(a)
        if href and title and not href.startswith("#"):
            _add(items, urljoin(page_url, href), title, rank=_title_rank(a))
    if not items:  # layout lạ: lấy link đầu tiên của mỗi block Book
        for row in scope.select("[itemtype*='Book']"):
            a = row.select_one("a[href]")
            if a and _anchor_title(a):
                _add(items, urljoin(page_url, a["href"]), _anchor_title(a), rank=_title_rank(a))
    return _finish(items)


def parse_catalog_genre(html, page_url: str, story_path_re: str,
                        selectors: Optional[Iterable[str]] = None) -> List[Item]:
    """Dùng cho metruyenchu/metruyencv/tangthuvien: thử selector cấu hình trước, rồi
    quét mọi <a> có path khớp ``story_path_re`` (loại link chương/thể loại/tác giả)."""
    soup = _soup(html)
    items: Dict[str, Item] = {}
    pat = re.compile(story_path_re)

    def ok(full: str) -> bool:
        path = urlsplit(full).path
        if any(x in path for x in ("/chuong-", "/the-loai/", "/tac-gia/", "/tim-kiem")):
            return False
        return bool(pat.fullmatch(path.rstrip("/")))

    for sel in (list(selectors) if selectors else []):
        try:
            anchors = soup.select(sel)
        except Exception:
            continue
        for a in anchors:
            full = urljoin(page_url, (a.get("href") or "").strip()).split("?")[0]
            if ok(full):
                _add(items, full, _anchor_title(a), rank=_title_rank(a))
        if items:
            return _finish(items)

    for a in soup.select("a[href]"):
        full = urljoin(page_url, (a.get("href") or "").strip()).split("?")[0]
        if ok(full):
            _add(items, full, _anchor_title(a), rank=_title_rank(a))
    return _finish(items)


METRUYENCHU_STORY_RE = r"/truyen/[^/]+"
TANGTHUVIEN_STORY_RE = r"/doc-truyen/[^/]+"
