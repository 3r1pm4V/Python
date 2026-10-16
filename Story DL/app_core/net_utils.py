"""Tiện ích mạng thuần Python (không phụ thuộc GUI/selenium) để dễ test.

Đặt tại ``app_core/net_utils.py``; ``HttpMixin._net_get_with_retry`` chỉ cần
uỷ quyền sang :func:`get_with_retry`.
"""
from __future__ import annotations

import random
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

RETRY_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})


def get_with_retry(
    session: Any,
    url: str,
    *,
    attempts: int = 3,
    backoff: float = 1.0,
    stream: bool = False,
    timeout: Tuple[int, int] = (5, 15),
    headers: Optional[Dict[str, str]] = None,
    label: str = "",
    log: Callable[[str], None] = lambda _msg: None,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """GET với exponential backoff.

    Khác bản cũ: ở lần thử cuối, nếu server vẫn trả 429/5xx thì trả về chính
    response đó (caller tự xét ``status_code``) thay vì ném
    ``RuntimeError("No attempts made")``; không ``sleep`` sau lần thử cuối.

    Args:
        session: đối tượng có ``.get(url, stream=, timeout=, headers=)``.
        attempts: tổng số lần gọi (>= 1).
        backoff: hệ số chờ cơ bản (giây); chờ = backoff * 2**i + jitter.

    Returns:
        Response của lần thử thành công, hoặc response cuối cùng.

    Raises:
        ValueError: ``attempts`` < 1.
        Exception: lỗi mạng của lần thử cuối nếu mọi lần đều lỗi.

    Complexity:
        O(attempts) request, O(1) bộ nhớ.
    """
    if attempts < 1:
        raise ValueError("attempts phải >= 1")

    for attempt in range(attempts):
        is_last = attempt == attempts - 1
        try:
            resp = session.get(url, stream=stream, timeout=timeout, headers=headers)
        except Exception as exc:  # noqa: BLE001 - session có thể là requests hoặc curl_cffi
            if is_last:
                raise
            reason = type(exc).__name__
        else:
            if is_last or resp.status_code not in RETRY_STATUS:
                return resp
            reason = f"HTTP {resp.status_code}"
            resp.close()  # trả connection về pool trước khi thử lại

        wait = backoff * (2 ** attempt) + random.uniform(0, 0.5)
        log(f"   ⚠️ {reason} {label} — thử lại sau {wait:.1f}s ({attempt + 1}/{attempts})")
        sleep(wait)

    raise RuntimeError("unreachable")  # pragma: no cover


def is_valid_epub(path: Path) -> bool:
    """Kiểm tra nhanh file có phải EPUB hợp lệ (ZIP, không rỗng).

    Bắt trường hợp tải về trang HTML (hết quota Drive, trang đăng nhập) nhưng
    được lưu thành ``.epub``.
    """
    try:
        return path.stat().st_size > 0 and zipfile.is_zipfile(path)
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Cloudflare / phân trang
# ---------------------------------------------------------------------------
_CF_CHALLENGE_MARKERS: Tuple[str, ...] = (
    "<title>just a moment",
    "<title>attention required",
    "cf-browser-verification",
    'id="challenge-form"',
    "_cf_chl_opt",
    "cf-chl-opt",
    "checking your browser before accessing",
    "enable javascript and cookies to continue",
)


def is_cloudflare_challenge(status_code: int, text: str) -> bool:
    """True nếu response là trang thử thách Cloudflare (không phải trang thật).

    Bản cũ dùng ``"cloudflare" in text.lower()`` nên báo nhầm với MỌI trang có
    nhắc đến ``cdnjs.cloudflare.com`` hoặc script ``/cdn-cgi/challenge-platform``
    (Cloudflare tự chèn vào trang bình thường) -> bỏ qua đường requests nhanh,
    hoặc ở tab Genre Copy thì trả về 0 truyện.
    """
    low = (text or "")[:60000].lower()
    if any(m in low for m in _CF_CHALLENGE_MARKERS):
        return True
    return status_code in (403, 429, 503) and "cloudflare" in low


def build_genre_page_url(base_url: str, page: int) -> str:
    """Dựng URL trang ``page`` của một thể loại (page 1 = URL gốc đã làm sạch).

    - truyenfull: ``.../trang-N/`` (tự bỏ hậu tố trang-N cũ nếu người dùng dán sẵn)
    - trichtinhlau / monkeydd / khosach.mnd / tangthuvien / metruyen*: ``?page=N``
      (thay tham số page cũ nếu có, giữ nguyên các tham số khác)
    - còn lại (dtv-ebook): trang 1 = ``<slug>.html``, trang N>=2 = ``<slug>/N.html``
    """
    import re
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

    url = base_url.strip()
    low = url.lower()
    if "truyenfull" in low:
        clean = re.sub(r"/trang-\d+/?$", "", url.rstrip("/"))
        return clean if page <= 1 else f"{clean}/trang-{page}/"

    if any(k in low for k in ("trichtinhlau.com", "monkeydd.com", "khosach.mnd.vn",
                              "tangthuvien.vn", "metruyenchu.com", "metruyencv.com")):
        if "monkeydd.com" in low:
            url = url.replace("www.", "")
        parts = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "page"]
        if page > 1:
            query.append(("page", str(page)))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    # dtv-ebook: trang 1 chính là <slug>.html, trang N>=2 là <slug>/N.html
    clean = re.sub(r"/\d+\.html$", "", url).replace(".html", "")
    return f"{clean}.html" if page <= 1 else f"{clean}/{page}.html"


# ---------------------------------------------------------------------------
# Proxy theo domain (vd. byedpi cho trichtinhlau.com)
# ---------------------------------------------------------------------------
PROXY_DOMAINS: Tuple[str, ...] = ("trichtinhlau.com",)
DEFAULT_BYEDPI_PROXY = "socks5://127.0.0.1:1080"


def normalize_proxy(raw: str) -> str:
    """'127.0.0.1:1080' -> 'socks5://127.0.0.1:1080'; rỗng -> ''. Giữ nguyên nếu đã có scheme."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    return raw if "://" in raw else f"socks5://{raw}"


def proxy_for_url(url: str, proxy: str, domains: Tuple[str, ...] = PROXY_DOMAINS) -> str:
    """Trả về proxy nếu ``url`` thuộc ``domains`` (kể cả subdomain), ngược lại ''."""
    from urllib.parse import urlsplit
    proxy = normalize_proxy(proxy)
    host = (urlsplit(url).hostname or "").lower()
    if proxy and any(host == d or host.endswith("." + d) for d in domains):
        return proxy
    return ""


def requests_proxies(url: str, proxy: str) -> Optional[Dict[str, str]]:
    """Dict ``proxies=`` cho requests. SOCKS dùng socks5h để DNS cũng đi qua proxy (cần PySocks)."""
    p = proxy_for_url(url, proxy)
    if not p:
        return None
    if p.startswith("socks5://"):
        p = "socks5h://" + p[len("socks5://"):]
    return {"http": p, "https": p}


def chrome_proxy_arg(proxy: str, domains: Tuple[str, ...] = PROXY_DOMAINS) -> str:
    """Cờ Chrome để CHỈ các ``domains`` đi qua proxy, site khác đi thẳng (qua PAC dạng data: URL).

    Không có DIRECT dự phòng cho domain đó: nếu byedpi chưa bật, Chrome báo
    ERR_PROXY_CONNECTION_FAILED (dễ nhận ra hơn ERR_CONNECTION_REFUSED mơ hồ).
    """
    import base64
    from urllib.parse import urlsplit
    proxy = normalize_proxy(proxy)
    if not proxy:
        return ""
    parts = urlsplit(proxy)
    scheme = {"socks5": "SOCKS5", "socks5h": "SOCKS5", "socks4": "SOCKS4",
              "http": "PROXY", "https": "HTTPS"}.get(parts.scheme, "SOCKS5")
    target = f"{scheme} {parts.hostname}:{parts.port or 1080}"
    conds = " || ".join(f'dnsDomainIs(host, "{d}") || host == "{d}"' for d in domains)
    pac = f'function FindProxyForURL(url, host) {{ if ({conds}) return "{target}"; return "DIRECT"; }}'
    b64 = base64.b64encode(pac.encode()).decode()
    return f"--proxy-pac-url=data:application/x-ns-proxy-autoconfig;base64,{b64}"
