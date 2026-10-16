"""Hàm thuần (không phụ thuộc GUI/selenium/constants) — dễ unit test.

Gồm: chuẩn hoá tên để so khớp file, chọn file khớp nhất, chọn link EPUB trong HTML,
và nhận diện tag Đam mỹ/BL theo TỪ NGUYÊN VẸN.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def normalize_for_match(text: str) -> str:
    """Chữ thường, NFC, mọi ký tự không phải chữ/số -> 1 dấu cách.

    Bản cũ dùng danh sách ký tự tiếng Việt viết tay (thiếu ``ĩ``, ``ũ``) và không
    chuẩn hoá NFC/NFD nên tên file từ macOS (NFD) không khớp tên trên web.
    """
    s = unicodedata.normalize("NFC", text or "").lower()
    return re.sub(r"[\W_]+", " ", s).strip()


def best_title_match(norm_title: str, index: Dict[str, Any]) -> Optional[Any]:
    """Tìm giá trị khớp nhất với ``norm_title`` trong ``index`` (khoá đã normalize).

    1. Khớp tuyệt đối.
    2. Khớp chứa theo RANH GIỚI TỪ (hai chiều), cả hai chuỗi >= 5 ký tự — bản cũ cho
       phép khoá ngắn bất kỳ (``"a"``) "nằm trong" mọi tiêu đề và lấy kết quả đầu tiên.
       Nếu nhiều ứng viên, chọn cái có độ dài gần tiêu đề nhất.
    """
    exact = index.get(norm_title)
    if exact is not None:
        return exact
    if len(norm_title) < 5:
        return None
    padded = f" {norm_title} "
    best, best_diff = None, None
    for key, value in index.items():
        if len(key) < 5:
            continue
        padded_key = f" {key} "
        if padded in padded_key or padded_key in padded:
            diff = abs(len(key) - len(norm_title))
            if best_diff is None or diff < best_diff:
                best, best_diff = value, diff
    return best


_CLOUD_HOSTS: Tuple[str, ...] = ("DRIVE.GOOGLE", "DOCS.GOOGLE", "BOX.COM", "MEDIAFIRE.COM")


def pick_epub_link(html: str, base_url: str) -> Optional[str]:
    """Chọn link tải EPUB tốt nhất trong trang sách (Drive > Box > Mediafire > link trực tiếp).

    Bản cũ so sánh ``".epub" in href.upper()`` (chữ thường với chuỗi đã upper) nên
    link nội bộ của site (``/download/...``) KHÔNG BAO GIỜ được nhận.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    candidates: List[Tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith(("javascript:", "mailto:")):
            continue
        text_upper = a.get_text().upper()
        h_upper = href.upper()
        td = a.find_parent("td")
        parent_td_text = td.get_text().upper() if td else ""
        is_epub = "EPUB" in text_upper or ".EPUB" in h_upper or "EPUB" in parent_td_text
        is_cloud = any(c in h_upper for c in _CLOUD_HOSTS)
        if not is_epub and not is_cloud:
            continue

        if "DRIVE.GOOGLE" in h_upper or "DOCS.GOOGLE" in h_upper:
            score = 100
        elif "BOX.COM" in h_upper:
            score = 90
        elif "MEDIAFIRE.COM" in h_upper:
            score = 80
        elif "DTV-EBOOK.COM.VN" in h_upper or href.startswith("/"):
            if ".EPUB" in h_upper or "DOWNLOAD" in h_upper:
                score = 40
            else:
                continue
        else:
            score = 50

        if "EPUB" in text_upper:
            score += 5
        candidates.append((score, urljoin(base_url, href)))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)  # sort ổn định: giữ thứ tự xuất hiện khi hoà điểm
    return candidates[0][1]


_DAM_MY_KEYWORDS: Tuple[str, ...] = (
    "đam mỹ", "dam my", "danmei", "boys love", "boys' love", "boyslove", "bl", "yaoi", "shounen ai",
)
_DAM_MY_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(k) for k in _DAM_MY_KEYWORDS) + r")(?!\w)"
)


def find_dam_my_tag(texts: Iterable[str]) -> Optional[str]:
    """Trả về chuỗi đầu tiên chứa tag Đam mỹ/BL, ngược lại ``None``.

    Khớp theo TỪ NGUYÊN VẸN: bản cũ dùng ``kw in txt`` nên ``"bl"`` khớp nhầm
    ``"blood"``, ``"problem"``, ``"fable"``... và loại oan rất nhiều truyện Wattpad.
    """
    for txt in texts:
        norm = unicodedata.normalize("NFC", txt or "").lower()
        if _DAM_MY_RE.search(norm):
            return txt
    return None


# ---------------------------------------------------------------------------
# Wattpad: lọc theo tag (Đam mỹ/BL) và trạng thái "Hoàn thành"
# ---------------------------------------------------------------------------

#: Tag khớp NGUYÊN CHUỖI (đã compact). "bl", "dm", "gay"... quá ngắn/mơ hồ để khớp chuỗi con.
BLOCKED_TAG_EXACT: frozenset[str] = frozenset({
    "bl", "dm", "gay", "mlm", "bxb", "boylove", "boyslove", "boyxboy", "boysxboys",
    "namxnam", "namnam", "yaoi", "danmei", "shounenai", "shonenai",
    "congthu", "nhatcongnhatthu", "dammy", "huynhde",
})
#: Chuỗi con đủ đặc trưng để khớp trong tag dài (vd: "dammyhiendai", "truyendammy").
BLOCKED_TAG_SUBSTRINGS: Tuple[str, ...] = ("dammy", "danmei", "boylove", "boyslove", "yaoi", "boyxboy", "huynhde")

_COMPLETED_RE = re.compile(r"(?<![a-z])(?:hoan thanh|hoan tat|completed|complete)(?![a-z])")
_NEGATED_COMPLETED_RE = re.compile(
    r"(?<![a-z])(?:chua|not|khong)\s+(?:hoan thanh|hoan tat|completed|complete)(?![a-z])"
)


def compact_tag(text: str) -> str:
    """Chuẩn hoá tag: bỏ dấu tiếng Việt, ``đ`` -> ``d``, chữ thường, chỉ giữ chữ-số.

    Ví dụ: ``"Đam Mỹ"``, ``"đammỹ"``, ``"dam-my"`` và ``"#DamMy"`` đều -> ``"dammy"``.
    Độ phức tạp: O(len(text)).
    """
    s = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-z]+", "", s)


def find_blocked_tag(tags: Iterable[str]) -> Optional[str]:
    """Trả về tag đầu tiên thuộc nhóm Đam mỹ/BL (nguyên văn), ngược lại ``None``.

    So khớp trên dạng compact: khớp nguyên chuỗi với ``BLOCKED_TAG_EXACT`` hoặc chứa
    một chuỗi trong ``BLOCKED_TAG_SUBSTRINGS``. Độ phức tạp: O(T) với T là tổng độ dài tag
    (số từ khoá là hằng số).
    """
    for tag in tags:
        key = compact_tag(str(tag))
        if not key:
            continue
        if key in BLOCKED_TAG_EXACT or any(sub in key for sub in BLOCKED_TAG_SUBSTRINGS):
            return str(tag)
    return None


def is_completed_label(text: str) -> bool:
    """``True`` nếu ``text`` là nhãn trạng thái hoàn thành ("Hoàn Thành", "Completed"...).

    Khớp theo TỪ NGUYÊN VẸN và loại trừ dạng phủ định: "Chưa hoàn thành", "Not completed",
    "Incomplete" đều trả về ``False``.
    """
    key = compact_words(text)
    if not key or _NEGATED_COMPLETED_RE.search(key):
        return False
    return _COMPLETED_RE.search(key) is not None


def compact_words(text: str) -> str:
    """Như :func:`compact_tag` nhưng GIỮ khoảng trắng giữa các từ (đã bỏ dấu, chữ thường)."""
    s = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-z]+", " ", s).strip()


# ---------------------------------------------------------------------------
# Lọc theo TIÊU ĐỀ: truyện không gắn tag Đam mỹ nhưng tên có "[BL]", "đm", "boylove"...
# ---------------------------------------------------------------------------

#: Từ đơn (đã bỏ dấu, khớp NGUYÊN TỪ). "đm"/"dm" cùng thành "dm". KHÔNG đưa "gay" vào đây:
#: bỏ dấu thì "gầy", "gáy" cũng thành "gay" -> xử lý riêng ở ``_TITLE_RAW_RE``.
BLOCKED_TITLE_WORDS: frozenset[str] = frozenset({
    "dm", "bl", "bxb", "boylove", "boyslove", "boyxboy", "boysxboys", "namxnam",
    "danmei", "yaoi", "dammy", "shounenai", "shonenai",
})
#: Cụm nhiều từ (đã bỏ dấu, các từ cách nhau 1 dấu cách; dấu nháy ' đã thành khoảng trắng).
BLOCKED_TITLE_PHRASES: Tuple[str, ...] = (
    "boy love", "boys love", "boy s love", "boys s love", "boy x boy", "boys x boys",
    "nam x nam", "shounen ai", "shonen ai", "nhat cong nhat thu", "nhat thu nhat cong",
)
#: Chuỗi con đủ đặc trưng để bắt dạng dính liền trong 1 từ (vd "truyendammy", "tieuthuyetyaoi").
BLOCKED_TITLE_SUBSTRINGS: Tuple[str, ...] = ("dammy", "danmei", "boylove", "boyslove", "boyxboy", "yaoi")

_TITLE_WORD_RE = re.compile(
    r"(?<![0-9a-z])(?:"
    + "|".join(re.escape(k) for k in sorted(BLOCKED_TITLE_PHRASES, key=len, reverse=True))
    + "|"
    + "|".join(re.escape(k) for k in sorted(BLOCKED_TITLE_WORDS, key=len, reverse=True))
    + r")(?![0-9a-z])"
)
#: Khớp trên chữ CÒN DẤU để tránh nhầm: "Đàm Mỹ Linh" (tên người) không khớp, "Đam Mỹ"/"dam my" thì có;
#: "gay" chỉ khớp khi đúng chữ không dấu (không dính "gầy", "gáy").
_TITLE_RAW_RE = re.compile(r"(?<!\w)(?:(?:đam|dam)[\s\-_.]*(?:mỹ|mĩ|my)|gay)(?!\w)")


def find_blocked_title(title: str) -> Optional[str]:
    """Trả về từ khoá BL tìm thấy trong ``title`` (để ghi log), ngược lại ``None``.

    Bắt các dạng: ``"[BL] ..."``, ``"(Đam Mỹ)"``, ``"ĐM"``, ``"dm"``, ``"Boy Love"``, ``"Boy x Boy"``,
    ``"BoyXBoy"``, ``"boy's love"``, ``"BXB"``, ``"yaoi"``... Khớp theo TỪ NGUYÊN VẸN nên
    ``"blood"``, ``"problem"``, ``"admin"``, ``"dmv"`` không bị loại oan.
    Độ phức tạp: O(len(title)).
    """
    if not title:
        return None
    raw = unicodedata.normalize("NFC", title).lower()
    m = _TITLE_RAW_RE.search(raw)
    if m:
        return m.group(0)
    spaced = compact_words(title)
    m = _TITLE_WORD_RE.search(spaced)
    if m:
        return m.group(0)
    for word in spaced.split():
        for sub in BLOCKED_TITLE_SUBSTRINGS:
            if sub in word:
                return sub
    return None


def parse_wattpad_story_page(
    html: str, status_selector: str, tags_selector: str,
) -> Tuple[Optional[bool], List[str]]:
    """Đọc trạng thái hoàn thành và danh sách tag từ HTML trang truyện Wattpad.

    Args:
        html: HTML trang ``/story/<id>``.
        status_selector: CSS selector ô trạng thái (vd ``div.GZxny:nth-child(1)``).
        tags_selector: CSS selector vùng tag (vd ``.uHKL3``).

    Returns:
        ``(completed, tags)``. ``completed`` là ``None`` nếu không tìm thấy ô trạng thái
        (để caller biết "không xác định" khác với "chưa hoàn thành").
    """
    soup = BeautifulSoup(html or "", "html.parser")

    completed: Optional[bool] = None
    status_el = soup.select_one(status_selector)
    if status_el is not None:
        completed = is_completed_label(status_el.get_text(" ", strip=True))

    tags: List[str] = []
    for area in soup.select(tags_selector):
        items = area.find_all("a") or [area]
        for el in items:
            txt = el.get_text(" ", strip=True).lstrip("#").strip()
            if txt and txt not in tags:
                tags.append(txt)
    return completed, tags


_WATTPAD_STORY_ID_RE = re.compile(r"/story/(\d+)")
_WATTPAD_TAG_PATH_RE = re.compile(r"^/stories/([^/?#]+)/?$")


def extract_wattpad_story_ids(html: str) -> List[str]:
    """Lấy ID truyện (``/story/<id>``) không trùng, giữ thứ tự xuất hiện. O(n)."""
    seen: Dict[str, None] = {}
    for sid in _WATTPAD_STORY_ID_RE.findall(html or ""):
        seen.setdefault(sid, None)
    return list(seen)


def parse_wattpad_tag_slug(url: str) -> Optional[str]:
    """Trả về slug tag từ URL dạng ``https://www.wattpad.com/stories/<tag>``, hoặc ``None``."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower()
    if parsed.scheme not in ("http", "https") or not (host == "wattpad.com" or host.endswith(".wattpad.com")):
        return None
    m = _WATTPAD_TAG_PATH_RE.match(parsed.path)
    return unquote(m.group(1)) if m else None


def parse_required_tags(text: str) -> List[str]:
    """Tách danh sách tag bắt buộc từ chuỗi người dùng nhập ("hvan, caoh" / "hvan;caoh" / "#hvan caoh")."""
    parts = re.split(r"[,;\n]+", text or "")
    out: List[str] = []
    for part in parts:
        tag = part.strip().lstrip("#").strip()
        if tag and tag not in out:
            out.append(tag)
    return out


def has_required_tag(tags: Iterable[str], required: Iterable[str]) -> bool:
    """``True`` nếu truyện có ÍT NHẤT MỘT tag bắt buộc (so khớp dạng compact: ``Cao H`` == ``caoh``).

    ``required`` rỗng nghĩa là không ràng buộc -> ``True``. Độ phức tạp O(T + R).
    """
    need = {compact_tag(r) for r in required if compact_tag(r)}
    if not need:
        return True
    return any(compact_tag(str(t)) in need for t in tags)


_WATTPAD_SEARCH_PATH_RE = re.compile(r"^/search/([^/?#]+)/?$")


def parse_wattpad_list_url(url: str) -> Optional[Tuple[str, str]]:
    """Nhận diện URL danh sách Wattpad: trả về ``("tag", slug)`` hoặc ``("search", từ_khoá)``.

    Hỗ trợ ``https://www.wattpad.com/stories/<tag>`` và ``https://www.wattpad.com/search/<từ khoá>``;
    URL khác (hoặc không phải wattpad.com) trả về ``None``.
    """
    from urllib.parse import unquote, urlparse

    tag = parse_wattpad_tag_slug(url)
    if tag:
        return "tag", tag
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower()
    if parsed.scheme not in ("http", "https") or not (host == "wattpad.com" or host.endswith(".wattpad.com")):
        return None
    m = _WATTPAD_SEARCH_PATH_RE.match(parsed.path)
    return ("search", unquote(m.group(1)).strip()) if m and m.group(1).strip() else None
