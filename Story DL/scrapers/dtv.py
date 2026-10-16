"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import logging

import re
from typing import Tuple

from bs4 import BeautifulSoup

from app_core.net_utils import is_cloudflare_challenge



_dbg = logging.getLogger(__name__)


class DtvMixin:
    def get_dtv_story_info(self, book_url: str) -> Tuple[str, str]:
        try:
            resp = self.http_session.get(book_url, timeout=(5, 10))
            if resp.status_code == 200 and not is_cloudflare_challenge(resp.status_code, resp.text):
                soup = BeautifulSoup(resp.content, "html.parser")
                
                title_el = soup.select_one("h1.title-detail, h1, .tensanpham h1")
                title = title_el.get_text(strip=True) if title_el else ""
                
                author = ""
                for row in soup.select("table tr, .thongtin-sach tr"):
                    row_text = row.get_text()
                    if "Tác giả" in row_text or "Tác Giả" in row_text:
                        cols = row.select("td")
                        if len(cols) >= 2:
                            author = cols[1].get_text(strip=True)
                        elif len(cols) == 1:
                            author = re.sub(r'Tác giả:\s*', '', cols[0].get_text(), flags=re.IGNORECASE).strip()
                        break
                return title, author
        except Exception:
            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

        try:
            driver = self.get_valid_driver()
            if self.normalize_url(driver.current_url) != self.normalize_url(book_url):
                driver.get(book_url)
                if not self.wait_for_cloudflare(): 
                    return "", ""

            title = driver.execute_script("""
                let el = document.querySelector('h1.title-detail, h1, .tensanpham h1');
                return el ? el.innerText.trim() : '';
            """) or ""

            author = driver.execute_script("""
                let rows = document.querySelectorAll('table tr, .thongtin-sach tr');
                for (let row of rows) {
                    if (row.innerText.includes('Tác giả') || row.innerText.includes('Tác Giả')) {
                        let cols = row.querySelectorAll('td');
                        if (cols.length >= 2) return cols[1].innerText.trim();
                        if (cols.length === 1) return cols[0].innerText.replace(/Tác giả:/i, '').trim();
                    }
                }
                return '';
            """) or ""

            return title, author
        except Exception as e:
            self.log(f"   ⚠️ Không lấy được thông tin chi tiết DTV: {str(e)[:50]}")
            return "", ""
