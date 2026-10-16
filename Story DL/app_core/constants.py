"""
Story Loader - hằng số, đường dẫn dữ liệu và selector mặc định
=============================================================================
A professional web scraper with GUI for downloading ebooks from multiple sources:
- dtv-ebook.com.vn
- monkeydd.com
- trichtinhlau.com
- docln.net / hako / ln.hako.vn
- truyenfull.live / truyenfull.vn
- wattpad.com
- khosach.mnd.vn
- metruyenchu.com / metruyencv.com
- tangthuvien.vn
- valvrareteam.com
- truyencv.org / sttruyen.com
"""

import re
import sys
import logging
from pathlib import Path
from typing import Tuple, Dict, Any

# Monkey-patch undetected_chromedriver và cấu hình logging nằm ở app_core/bootstrap.py
# (gọi từ main.py) để import constants không kéo theo selenium/uc -> dễ test.

# --- CONFIGURATION ---
APP_VERSION: str = "3.3.1"
# Khi đóng gói PyInstaller: dữ liệu người dùng nằm cạnh file .exe;
# khi chạy từ source: nằm ở thư mục gốc dự án (cha của app_core/).
BASE_PATH: Path = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
HISTORY_FILE: Path = BASE_PATH / "history.txt"
QUEUE_FILE: Path = BASE_PATH / "queue.txt"
# Truyện đã bị loại vĩnh viễn (tag/tiêu đề Đam mỹ/BL): lần chạy sau bỏ qua ngay, không gọi API nữa.
# Muốn kiểm tra lại 1 truyện: xoá dòng của nó (hoặc xoá cả file) trong blocked.txt.
BLOCKED_FILE: Path = BASE_PATH / "blocked.txt"
MAX_CONCURRENT_DOWNLOADS: int = 2
CONFIG_FILE: Path = BASE_PATH / "config.json"
SELECTORS_FILE: Path = BASE_PATH / "selectors.json"
TOKEN_FILE: Path = BASE_PATH / "token.json"
DEFAULT_OUTPUT_DIR: Path = BASE_PATH / "Story_Downloads"
BASE_URL = "https://dtv-ebook.com.vn"
MND_API_BASE = "https://khosach.mnd.vn/api"

# Precompiled regex for stripping invalid filesystem characters from filenames
INVALID_FS_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# --- DEFAULT SELECTORS ---
DEFAULT_SELECTORS: Dict[str, Any] = {
    "dtv": {
        "genre_book_links":   ["li.itemtruyen a", "h2.tensanpham a", "li.itemtruyen h2 a"],
        "book_genre_cell":    "tr:nth-child(8) > td:nth-child(2)",
        "epub_tab_text":      ["DOWNLOAD", "TẢI VỀ", "TẢI TRUYỆN"],
    },
    "monkeyd": {
        "story_container":    ".page-content > div:nth-child(1) > div:nth-child(5) > div:nth-child(1)",
        "story_container_fallback": ".page-content",
        "genre_cell":         "dd.col-sm-9:nth-child(8)",
        "status_cell":        "dd.col-sm-9:nth-child(18)",
        "chapter_content":    "#chapterContent, .chapter-content, .story-detail-content",
        "story_url_pattern":  "regex::^https?://(?:www\\.)?monkeydd\\.com/[^/]+\\.html$",
    },
    "trichtinhlau": {
        "book_links":         ["article.col-6 a[href*='/xem-truyen/']",
                               ".book-info h3 a[href*='/xem-truyen/']",
                               "a.book-item-name[href*='/xem-truyen/']",
                               ".truyen-item a[href*='/xem-truyen/']"],
        "genre_area":         "ul.list-unstyled",
        "chapter_links":      "a[href*='/doc-truyen/']",
        "chapter_content":    "#chapterContentDecoded, #chapterContent, .chapter-content, .post-content",
        "password_input":     "#passwordInput, input[type='password']",
    },
    "truyenfull": {
        "genre_book_links":   ["h3.title a", ".list-truyen h3.title a", ".truyen-title a"],
        "genre_container":    "div.col-sm-12:nth-child(1) > div:nth-child(2)",
        "story_title":        ".title",
        "chapter_links":      "#list-chapter .list-chapter a, #list-chapter a[href*='chuong']",
        "chapter_content":    "#chapter-c",
    },
    "hako": {
        "story_title":        "h1.series-name, .series-name, h1",
        "genre_links":        ".series-gernes a, .genre a, a[href*='the-loai']",
        "cover_image":        ".series-cover img, .novel-cover img, .cover img, img[src*='series']",
        "chapter_links":      "a.chapter-name, .list-chapters a[href*='/c'], a[href*='/chuong-']",
        "chapter_content":    "#chapter-content, .chapter-content, .content",
    },
    "khosachmnd": {
        "book_container":     "div#root div.grid",
        "book_item":          "div#root div.grid div.flex.flex-col.group",
        "epub_download":      "a.block:nth-child(4)",
        "story_title":        "h1, h2, h3, .title",
        "author":             ".author, .text-gray-500",
    },
    "mediafire": {
        "download_button":    "#downloadButton",
    },
    "metruyenchu": {
        "story_title":        ["h1.title", "h1.book-title", ".book-info h1", "h1"],
        "author":              ["a[href*='/tac-gia/']", ".author a"],
        "genres":              ["a[href*='/the-loai/']", ".categories a"],
        "cover_image":         [".book-img img", ".book-cover img", ".info-holder img"],
        "chapter_list_links":  ["a[href*='/chuong-']", ".chapters a", "#list-chapter a"],
        "chapter_content":     ["#chapter-content", ".chapter-content", ".content-chapter", ".box-chap"],
        "chapter_title":       [".chapter-title", "h2", "h1"],
        "next_page":           ["a.next", "a[rel='next']"],
        "genre_book_links":    ["h3 a[href*='/truyen/']", ".book-item a[href*='/truyen/']", "a.book-title"],
    },
    "tangthuvien": {
        "story_title":        ["h1.truyen-title", ".book-info h1", "h1"],
        "author":              [".info a[href*='tac-gia']", ".author a"],
        "genres":              [".info a[href*='the-loai']", ".categories a"],
        "cover_image":         [".book-img img", ".book img"],
        "chapter_list_links":  ["#j-bookCatalogPage a", ".list-chapter a", "a[href*='/doc-truyen/']"],
        "chapter_content":     [".box-chap", "#chapter-c", ".chapter-content"],
        "chapter_title":       [".chapter-title", "h2"],
        "genre_book_links":    [".book-img-text h4 a", ".update-list h4 a", "h4 a[href*='/doc-truyen/']"],
    },
    "valvrareteam": {
        "story_title":        ["h1.entry-title", "h1.post-title", "h1"],
        "author":              [".author-name", ".author a"],
        "genres":              [".cat-links a", ".entry-categories a"],
        "cover_image":         [".entry-content img", ".post-thumbnail img"],
        "chapter_list_links":  [".entry-content a[href*='/truyen/']", ".entry-content a"],
        "chapter_content":     [".entry-content", "#content"],
        "chapter_title":       ["h1.entry-title", "h2"],
    },
    "webdriver_wait_timeout": 4,
}

WATTPAD_API_BASE = "https://www.wattpad.com/api/v3"
WATTPAD_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.wattpad.com/",
    "X-Requested-With": "XMLHttpRequest",
}
WATTPAD_IMPERSONATE = "chrome124"
WATTPAD_CHAPTER_DELAY: Tuple[float, float] = (0.8, 2.0)
WATTPAD_WEB_BASE = "https://www.wattpad.com"
# Selector trên trang /story/<id>. Đây là class CSS đã băm (CSS-module) nên có thể đổi sau mỗi lần Wattpad
# deploy: chỉ cần sửa 2 dòng này. Chúng chỉ là phương án DỰ PHÒNG khi API không trả completed/tags.
WATTPAD_STATUS_SELECTOR = "div.GZxny:nth-child(1)"
WATTPAD_TAGS_SELECTOR = ".uHKL3"
WATTPAD_TAG_PAGE_DELAY: Tuple[float, float] = (1.0, 2.5)   # nghỉ giữa các lần lấy danh sách / giữa các truyện
WATTPAD_TAG_PAGE_SIZE = 30
WATTPAD_TAG_MISMATCH_ABORT = 10   # dừng nếu N truyện đầu liên tiếp đều không có tag bắt buộc
WATTPAD_TAG_MAX_PAGES = 200   # chặn vòng lặp vô hạn khi phân trang bất thường

GDRIVE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
}

logger = logging.getLogger(__name__)

