"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import logging

import customtkinter as ctk

import re
import threading
from typing import List
from urllib.parse import urljoin

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from app_core.constants import (
    INVALID_FS_CHARS_RE,
)


_dbg = logging.getLogger(__name__)


class MonkeydMixin:
    _genre_load_thread = None  # luồng nạp thể loại (dùng chung self.driver, không được chạy song song với luồng tải)

    def load_monkeyd_genres(self):
        # Selenium driver KHÔNG an toàn đa luồng: không nạp thể loại khi luồng tải đang dùng trình duyệt.
        worker = getattr(self, "_worker", None)
        if worker is not None and worker.is_alive():
            self.log("⚠️ Đang có tác vụ tải chạy (đang dùng trình duyệt) — hãy dừng hoặc đợi xong rồi mới nạp thể loại.")
            return
        if self._genre_load_thread is not None and self._genre_load_thread.is_alive():
            self.log("⏳ Đang nạp thể loại MonkeyD, vui lòng đợi...")
            return
        self.log("🔄 Đang tải danh sách thể loại từ MonkeyD...")
        def _load():
            try:
                driver = self.get_valid_driver()
                driver.get("https://www.monkeydd.com/")
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".nav-item.dropdown")))
                genre_elements = driver.find_elements(By.CSS_SELECTOR, "li.nav-item.dropdown ul.dropdown-menu.scroll-menu li a.dropdown-item")
                genres = sorted(list(set([e.text.strip() for e in genre_elements if e.text.strip()])))
                if not genres:
                    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/the-loai/']")
                    genres = sorted(list(set([l.text.strip() for l in links if l.text.strip() and l.text.strip() != "Thể loại"])))
                
                self.available_monkeyd_genres = genres
                self.log(f"✅ Đã tải {len(genres)} thể loại.")
                self.after(0, self._populate_monkeyd_genre_checkboxes)
            except Exception as e:
                self.log(f"❌ Lỗi tải thể loại: {e}")
        t = threading.Thread(target=_load, daemon=True)
        self._genre_load_thread = t
        t.start()

    def _populate_monkeyd_genre_checkboxes(self):
        for widget in self.monkeyd_genre_scroll.winfo_children(): widget.destroy()
        self.monkeyd_genre_checkboxes.clear()
        for idx, genre in enumerate(self.available_monkeyd_genres):
            var = ctk.BooleanVar()
            cb = ctk.CTkCheckBox(self.monkeyd_genre_scroll, text=genre, variable=var, font=("Inter", 9), height=18, fg_color=self.TEAL_PRIMARY)
            cb.pack(anchor="w", padx=5, pady=2)
            self.monkeyd_genre_checkboxes[genre.lower()] = var

    def is_monkeyd_completed(self) -> bool:
        COMPLETED_VALUES = ("đã đủ bộ", "hoàn thành", "đã hoàn thành")
        status_sel = self._sel("monkeyd", "status_cell") or "dd.col-sm-9:nth-child(18)"
        try:
            driver = self.get_valid_driver()
            try:
                elem = driver.find_element(By.CSS_SELECTOR, status_sel)
                text = elem.text.strip().lower()
                if any(x in text for x in COMPLETED_VALUES):
                    return True
                if text:
                    return False
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

            dt_elements = driver.find_elements(By.TAG_NAME, "dt")
            for dt in dt_elements:
                if any(label in dt.text.lower() for label in ["trạng thái", "tình trạng", "status"]):
                    try:
                        dd = dt.find_element(By.XPATH, "./following-sibling::dd[1]")
                        if any(x in dd.text.strip().lower() for x in COMPLETED_VALUES):
                            return True
                        elif dd.text.strip():
                            return False
                    except Exception:
                        _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
            return False
        except Exception:
            return False

    def extract_monkeyd_genres(self) -> List[str]:
        genre_sel = self._sel("monkeyd", "genre_cell") or "dd.col-sm-9:nth-child(8)"
        try:
            driver = self.get_valid_driver()
            try:
                genre_dd = driver.find_element(By.CSS_SELECTOR, genre_sel)
                genres = [a.text.strip() for a in genre_dd.find_elements(By.TAG_NAME, "a") if a.text.strip()]
                if genres:
                    return genres
                text = genre_dd.text.strip()
                if text:
                    return [t.strip() for t in text.split(",") if t.strip()]
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

            g_elements = driver.find_elements(By.CSS_SELECTOR, "dd a[href*='/the-loai/']")
            return [e.text.strip() for e in g_elements if e.text.strip() and e.text.strip().lower() != "thể loại"]
        except Exception:
            return []

    def _handle_monkeyd_ads(self):
        try:
            driver = self.get_valid_driver()
            try:
                ads = driver.find_elements(By.CSS_SELECTOR, ".affClick, a[href*='shopee.vn']")
                for ad in ads:
                    if ad.is_displayed():
                        driver.execute_script("arguments[0].click();", ad)
                        self._sleep(0.5)
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

            driver.execute_script("""
                try {
                    document.querySelectorAll('.affClick').forEach(el => {
                        el.click();
                        el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                    });
                    
                    document.querySelectorAll('.story-detail-content').forEach(el => {
                        el.style.display = 'block';
                        el.style.visibility = 'visible';
                        el.style.opacity = '1';
                    });
                } catch(e) {}
            """)
            self._sleep(1)
        except Exception:
            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

    def _clean_monkeyd_advertisement(self, content: str) -> str:
        patterns = [
            r"Mời Quý độc giả CLICK vào liên kết hoặc ảnh bên dưới mở ứng dụng Shopee để tiếp tục đọc toàn bộ chương truyện!.*?MonkeyD và đội ngũ Editor xin chân thành cảm ơn!",
            r"https://s\.shopee\.vn/[^\s]+",
            r"Quý độc giả.*?Shopee.*?tiếp tục đọc.*?truyện!",
            r"CLICK vào liên kết.*?Shopee.*?đọc toàn bộ chương truyện",
            r"MonkeyD và đội ngũ Editor.*?cảm ơn!",
        ]
        cleaned = content
        for p in patterns: cleaned = re.sub(p, "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        return re.sub(r'\n\s*\n\s*\n+', '\n\n', cleaned).strip()

    def process_monkeyd_story(self, url, idx, total, dest_dir, cache=None):
        try:
            driver = self.get_valid_driver()
            if self.normalize_url(driver.current_url) != self.normalize_url(url):
                driver = self._nav(url)
                self._sleep(1.5)
                if not self.wait_for_cloudflare(): return
                driver = self.get_valid_driver()  # wait_for_cloudflare có thể đã đổi sang Chrome thật
            
            try:
                story_name_raw = driver.find_element(By.CSS_SELECTOR, "h2, .story-title, h1").text.strip()
                story_name = INVALID_FS_CHARS_RE.sub('', story_name_raw)
            except Exception:
                story_name_raw = url.split('/')[-1].replace('.html', '').replace('-', ' ').title()
                story_name = INVALID_FS_CHARS_RE.sub('', story_name_raw)
            
            if self._is_blocked_title(story_name_raw, f"[{idx}/{total}]"):
                return

            if not self.overwrite_var.get() and self.check_epub_exists(dest_dir, story_name, cache):
                self.log(f"[{idx}/{total}] Bỏ qua: {story_name} (File đã tồn tại)")
                self.save_history(url)
                return

            self.log(f"[{idx}/{total}] MonkeyD: {story_name}")
            cover_data = None
            try:
                cover_url = None
                cover_selectors = [
                    ".page-content .img-fluid",
                    ".story-detail .img-fluid",
                    ".img-fluid",
                ]
                for sel in cover_selectors:
                    imgs = driver.find_elements(By.CSS_SELECTOR, sel)
                    for img in imgs:
                        src = img.get_attribute("src") or ""
                        if src and not any(x in src.lower() for x in ["logo", "icon", "favicon", "avatar", "banner"]):
                            cover_url = src
                            break
                    if cover_url:
                        break
                if cover_url:
                    if not cover_url.startswith("http"): cover_url = urljoin("https://www.monkeydd.com", cover_url)
                    resp = self.http_session.get(cover_url, timeout=(5, 15))
                    if resp.status_code == 200: cover_data = resp.content
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

            def _set_images_enabled(enabled: bool) -> None:
                try:
                    driver.execute_cdp_cmd(
                        "Network.setBlockedURLs",
                        {"urls": [] if enabled else ["*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.svg"]}
                    )
                except Exception:
                    _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

            chapter_links = []
            slug = url.split('/')[-1].replace('.html', '')
            links = driver.find_elements(By.CSS_SELECTOR, f"a[href*='/{slug}/']")
            for l in links:
                h = l.get_attribute("href")
                if h and f"/{slug}/" in h and h not in chapter_links:
                    if not h.startswith("http"): h = urljoin("https://www.monkeydd.com", h)
                    chapter_links.append(h)
            chapter_links.sort(key=lambda u: int(re.search(r'(\d+)', u.split('/')[-1]).group(1)) if re.search(r'(\d+)', u.split('/')[-1]) else 0)

            if not chapter_links: return self.log("   - ⚠️ No chapters")

            _set_images_enabled(False)
            driver.implicitly_wait(0)
            CONTENT_SELECTOR = self._sel("monkeyd", "chapter_content") or "#chapterContent, .chapter-content, .story-detail-content"

            chapters_data = []
            self.queue_add(url)
            for i, c_url in enumerate(chapter_links, 1):
                if not self.is_running: break
                driver = self._nav(c_url)

                try:
                    WebDriverWait(driver, self._wdwait()).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, CONTENT_SELECTOR))
                    )
                except TimeoutException:
                    if not self.wait_for_cloudflare(): continue
                    driver = self.get_valid_driver()  # driver cũ có thể đã bị thay bằng Chrome thật

                self._handle_monkeyd_ads()

                try:
                    el = driver.find_element(By.CSS_SELECTOR, CONTENT_SELECTOR)
                    content_text = self._clean_monkeyd_advertisement(self.extract_text_with_pseudo_elements(el))

                    if len(content_text) < 200 or "click" in content_text.lower():
                        self._handle_monkeyd_ads()
                        try:
                            WebDriverWait(driver, 3).until(
                                lambda d: len(d.find_element(By.CSS_SELECTOR, CONTENT_SELECTOR).text) > 200
                            )
                        except Exception:
                            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
                        el = driver.find_element(By.CSS_SELECTOR, CONTENT_SELECTOR)
                        content_text = self._clean_monkeyd_advertisement(self.extract_text_with_pseudo_elements(el))

                    chapters_data.append((f"Chương {i}", content_text))
                except Exception:
                    chapters_data.append((f"Chương {i}", "[Lỗi nội dung]"))
                if i % 10 == 0 or i == len(chapter_links): self.log(f"   ↳ {i}/{len(chapter_links)}...")
                self._set_progress(((idx - 1) / total) + ((i / len(chapter_links)) * (1 / total)))

            _set_images_enabled(True)
            driver.implicitly_wait(2)

            if chapters_data:
                if not self.is_running:
                    self.log(f"⏹ Đã dừng — '{story_name}' chưa hoàn tất, các chương đã tải chưa được lưu nên lần sau sẽ tải lại từ đầu.")
                else:
                    if self.create_epub(story_name, chapters_data, dest_dir, cover_data):
                        self.save_history(url)
                        self.queue_remove(url)
        except Exception as e: self.log(f"   - ❌ Lỗi MonkeyD: {str(e)[:50]}")
