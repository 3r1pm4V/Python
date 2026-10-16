"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import logging

import re
from pathlib import Path
from typing import List, Tuple, Optional, Set, Dict, Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app_core.genre_parsers import parse_truyenfull_genre
from app_core.constants import (
    INVALID_FS_CHARS_RE,
)


_dbg = logging.getLogger(__name__)


class TruyenFullMixin:
    def _get_truyenfull_genre_links_with_titles(self, genre_url: str) -> List[Dict[str, str]]:
        try:
            html = self._fetch_genre_html(genre_url, site_key="truyenfull")
            items = parse_truyenfull_genre(html, genre_url) if html else []
            self.log(f"   ✅ [Truyện Full] Quét được {len(items)} truyện từ thể loại.")
            return items
        except Exception as e:
            self.log(f"   ⚠️ Lỗi quét danh sách thể loại Truyện Full: {str(e)[:60]}")
            return []

    def get_truyenfull_story_info(self, url: str) -> Dict[str, Any]:
        info: Dict[str, Any] = {"title": "", "author": "", "genres": [], "status": "", "cover_url": ""}
        try:
            resp = self._net_get_with_retry(self.http_session, url, timeout=(5, 15), label="truyenfull")
            soup = BeautifulSoup(resp.content, "html.parser")

            title_el = soup.select_one("h3.title, .book h3, h1.title, h1, .title")
            if title_el:
                info["title"] = title_el.get_text(strip=True)

            author_el = soup.select_one(".info > div:nth-child(1) a[href*='/tac-gia/']")
            if author_el:
                info["author"] = author_el.get_text(strip=True)

            info["genres"] = [
                g.get_text(strip=True)
                for g in soup.select(".info > div:nth-child(2) a[href*='/the-loai/']")
                if g.get_text(strip=True)
            ]

            status_div = soup.select_one(".info > div:nth-child(3)")
            if status_div:
                status_text = status_div.get_text(strip=True)
                info["status"] = re.sub(r"^Trạng\s*thái\s*:?\s*", "", status_text, flags=re.IGNORECASE).strip()

            cover_el = soup.select_one(".book img")
            if cover_el and cover_el.get("src"):
                info["cover_url"] = cover_el["src"]
        except Exception as e:
            self.log(f"   ⚠️ Lỗi lấy thông tin truyện Truyện Full: {str(e)[:60]}")
        return info

    def get_truyenfull_chapter_links(self, story_url: str) -> List[str]:
        """Lấy toàn bộ link chương của Truyện Full (xử lý chính xác input hidden #total-page và quyển/chương)."""
        links: List[str] = []
        seen: Set[str] = set()
        
        clean_story_url = story_url.split('?')[0].rstrip('/') + '/'
        
        try:
            resp = self._net_get_with_retry(
                self.http_session, clean_story_url, timeout=(5, 15), label="truyenfull-chlist-p1"
            )
            if resp.status_code != 200:
                return links
            
            soup = BeautifulSoup(resp.content, "html.parser")
            
            # Read total pages from hidden input (e.g. <input id="total-page" value="41">)
            total_pages = 1
            total_page_input = soup.select_one("input#total-page")
            if total_page_input and total_page_input.get("value"):
                try:
                    total_pages = int(total_page_input["value"])
                except ValueError:
                    total_pages = 1
            else:
                last_page_a = soup.select_one(".pagination a[title*='Trang '], .pagination a[title*='Cuối']")
                if last_page_a:
                    m = re.search(r'trang-(\d+)', last_page_a.get("href", ""))
                    if m:
                        total_pages = int(m.group(1))

            self.log(f"   📑 [Truyện Full] Tổng số trang danh sách chương: {total_pages}")

            for page in range(1, total_pages + 1):
                if not self.is_running:
                    break

                page_url = clean_story_url if page == 1 else f"{clean_story_url}trang-{page}/"
                
                if page > 1:
                    try:
                        resp = self._net_get_with_retry(
                            self.http_session, page_url, timeout=(5, 15), label=f"truyenfull-chlist-p{page}"
                        )
                        if resp.status_code != 200:
                            break
                        soup = BeautifulSoup(resp.content, "html.parser")
                    except Exception as p_err:
                        self.log(f"   ⚠️ Lỗi lấy danh sách chương trang {page}: {p_err}")
                        break

                chapter_a_tags = soup.select("#list-chapter .list-chapter a, #list-chapter a[href*='chuong']")
                if not chapter_a_tags:
                    chapter_a_tags = soup.select(".list-chapter a")

                page_added = 0
                for a in chapter_a_tags:
                    href = a.get("href")
                    if href:
                        full_href = urljoin(page_url, href)
                        full_href = full_href.split('#')[0]
                        if full_href not in seen and clean_story_url in full_href:
                            seen.add(full_href)
                            links.append(full_href)
                            page_added += 1

                if page_added == 0 and page > 1:
                    break

                self._sleep(0.3, 0.8)

        except Exception as e:
            self.log(f"   ⚠️ Lỗi quét danh sách chương Truyện Full: {str(e)[:80]}")

        return links

    def get_truyenfull_chapter_content(self, chapter_url: str) -> str:
        try:
            resp = self._net_get_with_retry(
                self.http_session, chapter_url, timeout=(5, 20), label="truyenfull-chapter"
            )
            soup = BeautifulSoup(resp.content, "html.parser")
            
            container = (
                soup.select_one("#chapter-c")
                or soup.select_one(".chapter-c")
                or soup.select_one("#chapter-content")
                or soup.select_one(".chapter-content")
            )
            if not container:
                return ""

            chapter_title = ""
            title_el = soup.select_one(".chapter-title, h2.chapter-title, h2, h1")
            if title_el:
                chapter_title = title_el.get_text(strip=True)

            for junk in container.select("script, style, .ads, [id*='ads'], [class*='ads'], .box-notice"):
                junk.decompose()

            paragraphs = []
            for p in container.find_all("p"):
                style = p.get("style", "").lower()
                if "display: none" in style or "visibility: hidden" in style or "height: 0" in style:
                    continue
                
                p_text = p.get_text("\n", strip=True)
                if p_text:
                    paragraphs.append(p_text)

            content_text = "\n\n".join(paragraphs)
            
            if not content_text:
                content_text = container.get_text("\n", strip=True)

            if chapter_title and not content_text.startswith(chapter_title):
                final_content = f"# {chapter_title}\n\n{content_text}"
            else:
                final_content = content_text

            return final_content.strip()
        except Exception as e:
            self.log(f"   ⚠️ Lỗi tải chương ({chapter_url}): {str(e)[:60]}")
            return ""

    def process_truyenfull_story(self, url: str, idx: int, total: int, dest_dir: Path, cache: Optional[Set[str]] = None) -> None:
        try:
            info = self.get_truyenfull_story_info(url)
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
                self.log(f"[{idx}/{total}] Bỏ qua: Thể loại Đam mỹ (Truyện Full).")
                return

            self.log(f"[{idx}/{total}] Đang xử lý: {story_name}")
            self.queue_add(url)

            chapter_links = self.get_truyenfull_chapter_links(url)
            if not chapter_links:
                self.log(f"   ⚠️ Không tìm thấy chương nào cho {story_name}")
                return

            self.log(f"   - Tìm thấy {len(chapter_links)} chương. Đang tải nội dung...")

            cover_data: Optional[bytes] = None
            cover_url = info.get("cover_url")
            if cover_url:
                try:
                    cover_resp = self._net_get_with_retry(
                        self.http_session, cover_url, timeout=(5, 15), label="truyenfull-cover"
                    )
                    if cover_resp.status_code == 200:
                        cover_data = cover_resp.content
                except Exception:
                    _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

            chapters_data: List[Tuple[str, str]] = []
            for i, c_link in enumerate(chapter_links, 1):
                if not self.is_running:
                    break
                content = self.get_truyenfull_chapter_content(c_link)
                chapters_data.append((f"Chương {i}", content or "[Không tải được nội dung]"))
                if i % 20 == 0 or i == len(chapter_links):
                    self.log(f"   ↳ Đã tải {i}/{len(chapter_links)} chương")
                self._sleep(0.8, 1.5)

            if not self.is_running:
                self.log(f"⏹ Đã dừng — '{story_name}' chưa hoàn tất, các chương đã tải chưa được lưu nên lần sau sẽ tải lại từ đầu.")
                return

            if self.create_epub(story_name, chapters_data, dest_dir, cover_data, author=info.get("author", "")):
                self.save_history(url, story_name)
                self.queue_remove(url)
        except Exception as e:
            self.log(f"   ❌ Lỗi xử lý Truyện Full: {str(e)[:100]}")
