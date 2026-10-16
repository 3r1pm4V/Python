"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import logging

from pathlib import Path
from typing import List, Tuple, Optional, Set, Dict, Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app_core.constants import (
    INVALID_FS_CHARS_RE, DEFAULT_SELECTORS,
)


_dbg = logging.getLogger(__name__)


class MetruyenchuMixin:
    def get_metruyenchu_story_info(self, url: str) -> Dict[str, Any]:
        info: Dict[str, Any] = {"title": "", "author": "", "genres": [], "cover_url": ""}
        sel = self._selectors.get("metruyenchu", DEFAULT_SELECTORS["metruyenchu"])
        try:
            resp = self._net_get_with_retry(self.http_session, url, timeout=(5, 15), label="metruyenchu")
            soup = BeautifulSoup(resp.content, "html.parser")

            title_el = self._select_first(soup, sel["story_title"])
            if title_el:
                info["title"] = title_el.get_text(strip=True)

            author_el = self._select_first(soup, sel["author"])
            if author_el:
                info["author"] = author_el.get_text(strip=True)

            for gsel in sel["genres"]:
                try:
                    info["genres"] = [g.get_text(strip=True) for g in soup.select(gsel) if g.get_text(strip=True)]
                    if info["genres"]:
                        break
                except Exception:
                    continue

            cover_el = self._select_first(soup, sel["cover_image"])
            if cover_el and cover_el.get("src"):
                info["cover_url"] = urljoin(url, cover_el["src"])
        except Exception as e:
            self.log(f"   ⚠️ Lỗi lấy thông tin truyện MeTruyenChu: {str(e)[:60]}")
        return info

    def get_metruyenchu_chapter_links(self, story_url: str) -> List[str]:
        sel = self._selectors.get("metruyenchu", DEFAULT_SELECTORS["metruyenchu"])
        links: List[str] = []
        seen: Set[str] = set()
        page_url = story_url
        page = 1
        while self.is_running and page_url:
            try:
                resp = self._net_get_with_retry(self.http_session, page_url, timeout=(5, 15), label="metruyenchu-chlist")
            except Exception:
                break
            if resp.status_code != 200:
                break

            soup = BeautifulSoup(resp.content, "html.parser")
            page_links = []
            for lsel in sel["chapter_list_links"]:
                for a in soup.select(lsel):
                    href = a.get("href")
                    if href:
                        href = urljoin(page_url, href)
                        if href not in seen:
                            seen.add(href)
                            page_links.append(href)
                if page_links:
                    break

            if not page_links:
                break
            links.extend(page_links)

            next_el = self._select_first(soup, sel.get("next_page", []))
            next_href = next_el.get("href") if next_el else None
            if not next_href:
                break
            page_url = urljoin(page_url, next_href)
            page += 1
            self._sleep(1.0, 2.0)

        return links

    def get_metruyenchu_chapter_content(self, chapter_url: str) -> str:
        sel = self._selectors.get("metruyenchu", DEFAULT_SELECTORS["metruyenchu"])
        try:
            resp = self._net_get_with_retry(self.http_session, chapter_url, timeout=(5, 20), label="metruyenchu-chapter")
            soup = BeautifulSoup(resp.content, "html.parser")

            container = self._select_first(soup, sel["chapter_content"])
            if not container:
                return ""

            for junk in container.select("script, style, .ads, [id*='ads'], [class*='ads']"):
                junk.decompose()

            chapter_title = ""
            title_el = self._select_first(soup, sel["chapter_title"])
            if title_el:
                chapter_title = title_el.get_text(strip=True)

            paragraphs = self._extract_visible_paragraphs(container)
            content_text = "\n\n".join(paragraphs) if paragraphs else container.get_text("\n", strip=True)

            if chapter_title and not content_text.startswith(chapter_title):
                return f"# {chapter_title}\n\n{content_text}".strip()
            return content_text.strip()
        except Exception as e:
            self.log(f"   ⚠️ Lỗi tải chương MeTruyenChu ({chapter_url}): {str(e)[:60]}")
            return ""

    def process_metruyenchu_story(self, url: str, idx: int, total: int, dest_dir: Path, cache: Optional[Set[str]] = None) -> None:
        try:
            info = self.get_metruyenchu_story_info(url)
            story_name_raw = info.get("title") or url.rstrip("/").split("/")[-1].replace("-", " ").title()
            story_name = INVALID_FS_CHARS_RE.sub('', story_name_raw).strip()

            if self._is_blocked_title(story_name_raw, f"[{idx}/{total}]"):
                return

            if not self.overwrite_var.get() and self.is_story_already_downloaded(url, dest_dir, story_name, cache):
                self.log(f"[{idx}/{total}] Bỏ qua: {story_name} (Đã có file)")
                self.save_history(url, story_name)
                return

            genres_lower = [g.lower() for g in info.get("genres", [])]
            if any("đam mỹ" in g for g in genres_lower):
                self.log(f"[{idx}/{total}] Bỏ qua: Thể loại Đam mỹ (MeTruyenChu).")
                return

            self.log(f"[{idx}/{total}] Đang xử lý (MeTruyenChu): {story_name}")
            self.queue_add(url)

            chapter_links = self.get_metruyenchu_chapter_links(url)
            if not chapter_links:
                self.log(f"   ⚠️ Không tìm thấy chương nào cho {story_name} — kiểm tra lại selectors.json['metruyenchu']")
                return

            self.log(f"   - Tìm thấy {len(chapter_links)} chương. Đang tải nội dung...")

            cover_data: Optional[bytes] = None
            cover_url = info.get("cover_url")
            if cover_url:
                try:
                    cover_resp = self._net_get_with_retry(self.http_session, cover_url, timeout=(5, 15), label="metruyenchu-cover")
                    if cover_resp.status_code == 200:
                        cover_data = cover_resp.content
                except Exception:
                    _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

            chapters_data: List[Tuple[str, str]] = []
            for i, c_link in enumerate(chapter_links, 1):
                if not self.is_running:
                    break
                content = self.get_metruyenchu_chapter_content(c_link)
                chapters_data.append((f"Chương {i}", content or "[Không tải được nội dung]"))
                if i % 20 == 0 or i == len(chapter_links):
                    self.log(f"   ↳ Đã tải {i}/{len(chapter_links)} chương")
                self._sleep(1.0, 2.0)

            if not self.is_running:
                self.log(f"⏹ Đã dừng — '{story_name}' chưa hoàn tất, các chương đã tải chưa được lưu nên lần sau sẽ tải lại từ đầu.")
                return

            if self.create_epub(story_name, chapters_data, dest_dir, cover_data, author=info.get("author", "")):
                self.save_history(url, story_name)
                self.queue_remove(url)
        except Exception as e:
            self.log(f"   ❌ Lỗi xử lý MeTruyenChu: {str(e)[:100]}")
