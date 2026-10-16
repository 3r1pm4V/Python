"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import logging


from selenium.webdriver.common.by import By

from app_core.constants import (
    INVALID_FS_CHARS_RE,
)


_dbg = logging.getLogger(__name__)


class HakoMixin:
    def process_hako_story(self, url, idx, total, dest_dir, cache=None):
        try:
            driver = self._nav(url)
            self._sleep(2)
            if not self.wait_for_cloudflare(): return
            driver = self.get_valid_driver()  # wait_for_cloudflare có thể đã đổi sang Chrome thật

            self.log(f"[{idx}/{total}] Hako: {url}")
            story_title = ""
            try:
                story_title = driver.find_element(By.CSS_SELECTOR, "h1.series-name, .series-name, h1").text.strip()
                story_name = INVALID_FS_CHARS_RE.sub('', story_title)
            except Exception:
                story_name_raw = url.split('/')[-1].replace('.html', '').replace('-', ' ').title()
                story_name = INVALID_FS_CHARS_RE.sub('', story_name_raw)

            if self._is_blocked_title(story_title or story_name, f"[{idx}/{total}]"):
                return

            if not self.overwrite_var.get() and self.check_epub_exists(dest_dir, story_name, cache):
                self.log(f"[{idx}/{total}] Bỏ qua: {story_name} (Đã có file)")
                self.save_history(url)
                return

            try:
                genres_elements = driver.find_elements(By.CSS_SELECTOR, ".series-gernes a, .genre a, a[href*='the-loai']")
                genres = [g.text.strip().lower() for g in genres_elements if g.text.strip()]
                if any("đam mỹ" in g for g in genres):
                    self.log(f"[{idx}/{total}] Bỏ qua: Thể loại Đam mỹ (Hako).")
                    return
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

            cover_data = None
            try:
                img_selectors = [".series-cover img", ".novel-cover img", ".cover img", "img[src*='series']"]
                cover_url = None
                for sel in img_selectors:
                    try:
                        img_el = driver.find_element(By.CSS_SELECTOR, sel)
                        cover_url = img_el.get_attribute("src")
                        if cover_url: break
                    except Exception:
                        continue
                if cover_url:
                    if cover_url.startswith("//"): cover_url = "https:" + cover_url
                    resp = self.http_session.get(cover_url, timeout=(5, 15))
                    if resp.status_code == 200: cover_data = resp.content
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

            self.log("   📑 Đang trích xuất danh sách chương Hako...")
            
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            self._sleep(1)

            try:
                see_more_buttons = driver.find_elements(By.CSS_SELECTOR, ".see_more, .see-more, .mobile-more")
                for btn in see_more_buttons:
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        self._sleep(0.5)
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

            chapter_links = []
            processed_urls = set()
            
            chapters_elements = driver.find_elements(By.CSS_SELECTOR, "a.chapter-name, .list-chapters a[href*='/c'], a[href*='/chuong-']")
            for link in chapters_elements:
                try:
                    c_url = link.get_attribute("href")
                    if c_url and c_url not in processed_urls and any(kw in c_url.lower() for kw in ['chuong', 'chapter', '/c']):
                        c_title = link.text.strip() or f"Chương {len(chapter_links) + 1}"
                        chapter_links.append((c_title, c_url))
                        processed_urls.add(c_url)
                except Exception:
                    continue

            if not chapter_links:
                return self.log("   - ⚠️ Không tìm thấy chương nào")

            self.log(f"   - Tìm thấy {len(chapter_links)} chương. Đang cào nội dung...")
            
            chapters_data = []
            self.queue_add(url)
            for i, (c_title, c_url) in enumerate(chapter_links, 1):
                if not self.is_running: break
                
                driver = self._nav(c_url)
                self._sleep(1.5, 2.5)
                if not self.wait_for_cloudflare(): continue
                driver = self.get_valid_driver()
                
                try:
                    content_elem = None
                    for selector in ['#chapter-content', '.chapter-content', '.content']:
                        try:
                            content_elem = driver.find_element(By.CSS_SELECTOR, selector)
                            if content_elem: break
                        except Exception:
                            continue
                    
                    if content_elem:
                        try:
                            driver.execute_script("""
                                document.querySelectorAll('h6.title-item, a[href*="shopee.vn"], .ads-container, script, ins').forEach(el => el.remove());
                            """)
                        except Exception:
                            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
                        
                        html_content = content_elem.get_attribute('innerHTML')
                        chapters_data.append((c_title, html_content))
                    else:
                        chapters_data.append((c_title, "[Không tìm thấy nội dung]"))
                except Exception:
                    chapters_data.append((c_title, "[Lỗi cào nội dung]"))
                
                if i % 10 == 0 or i == len(chapter_links): self.log(f"   ↳ {i}/{len(chapter_links)}...")
                self._set_progress(((idx - 1) / total) + ((i / len(chapter_links)) * (1 / total)))

            if chapters_data:
                if not self.is_running:
                    self.log(f"⏹ Đã dừng — '{story_name}' chưa hoàn tất, các chương đã tải chưa được lưu nên lần sau sẽ tải lại từ đầu.")
                else:
                    if self.create_epub(story_name, chapters_data, dest_dir, cover_data):
                        self.save_history(url)
                        self.queue_remove(url)
                        self.log(f"   ✅ Hoàn thành: {story_name}")

        except Exception as e:
            self.log(f"   - ❌ Lỗi Hako: {str(e)[:50]}")
