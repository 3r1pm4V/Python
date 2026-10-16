"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import logging

import re

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app_core.net_utils import requests_proxies
from app_core.constants import (
    INVALID_FS_CHARS_RE,
)


_dbg = logging.getLogger(__name__)


class TrichTinhLauMixin:
    def process_trichtinhlau_story(self, url, idx, total, dest_dir):
        try:
            driver = self._nav(url)
            self._sleep(2)
            if not self.wait_for_cloudflare(): return
            driver = self.get_valid_driver()  # wait_for_cloudflare có thể đã đổi sang Chrome thật
            
            try:
                h1 = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
                raw_name = h1.text.strip()
                story_name = INVALID_FS_CHARS_RE.sub('', raw_name)
            except Exception:
                story_name_raw = url.split('/')[-1].replace('.html', '').replace('-', ' ').title()
                story_name = INVALID_FS_CHARS_RE.sub('', story_name_raw)

            if self._is_blocked_title(story_name, f"[{idx}/{total}]"):
                return

            if not self.overwrite_var.get() and self.check_epub_exists(dest_dir, story_name):
                self.log(f"[{idx}/{total}] Bỏ qua: {story_name} (Đã có file trong thư mục)")
                self.save_history(url)
                return

            try:
                genre_area = driver.find_element(By.CSS_SELECTOR, "ul.list-unstyled")
                genre_text = genre_area.text.lower()
                if "đam mỹ" in genre_text:
                    self.log(f"[{idx}/{total}] Bỏ qua: Thể loại Đam mỹ (Trích Tinh Lâu).")
                    return
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

            cover_data = None
            try:
                cover_selectors = [".book3d > img", ".book-info .img-responsive", "img[alt='" + story_name + "']"]
                cover_url = None
                for sel in cover_selectors:
                    try:
                        img_el = driver.find_element(By.CSS_SELECTOR, sel)
                        cover_url = img_el.get_attribute("src")
                        if cover_url: break
                    except Exception:
                        continue
                
                if cover_url:
                    self.log(f"   - 🖼️ Đang tải cover: {cover_url.split('/')[-1]}")
                    resp = self.http_session.get(cover_url, timeout=(5, 15),
                                                 proxies=requests_proxies(cover_url, self._site_proxy()))
                    if resp.status_code == 200:
                        cover_data = resp.content
            except Exception as e:
                self.log(f"   - ⚠️ Không tải được cover: {str(e)[:50]}")

            self.log(f"[{idx}/{total}] Đang xử lý: {story_name}")
            
            chapter_links = []
            self.queue_add(url)
            while self.is_running:
                try:
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/doc-truyen/']")))
                    before = len(chapter_links)
                    elems = driver.find_elements(By.CSS_SELECTOR, "a[href*='/doc-truyen/']")
                    for e in elems:
                        href = e.get_attribute("href")
                        if href and "/chuong-" in href and href not in chapter_links:
                            chapter_links.append(href)
                    if len(chapter_links) == before:
                        break  # trang này không thêm chương mới -> hết trang (tránh lặp vô hạn khi nút Next luôn tồn tại)

                    next_btns = driver.find_elements(By.CSS_SELECTOR, ".pagination a[rel='next']")
                    if next_btns:
                        driver.execute_script("arguments[0].click();", next_btns[0])
                        self._sleep(2)
                    else: break
                except Exception:
                    break

            if not chapter_links:
                self.log("   - ⚠️ Không tìm thấy chương nào")
                return

            self.log(f"   - Tìm thấy {len(chapter_links)} chương. Đang cào nội dung...")
            
            chapters_data = []
            known_passwords = {"1"}
            last_successful_password = None
            has_invalid_password = False

            decode_js = """
            function extractTextFromNode(node) {
                if (!node) return "";
                if (node.nodeType === Node.TEXT_NODE) return node.textContent;
                if (node.nodeType !== Node.ELEMENT_NODE) return "";
                
                if (node.classList.contains('no-copy-word')) {
                    return node.getAttribute('data-text') || "";
                }

                let style = window.getComputedStyle(node);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0' || style.fontSize === '0px') {
                    if (node.id !== 'chapterContent') return "";
                }

                let text = "";
                let tagName = node.tagName.toUpperCase();

                if (tagName === 'BR') return "\\n";

                for (let child of node.childNodes) {
                    text += extractTextFromNode(child);
                }

                if (['P', 'DIV', 'H1', 'H2', 'H3', 'H4', 'H5', 'LI', 'TR'].includes(tagName)) {
                    text += "\\n";
                }

                return text;
            }
            let container = document.querySelector('#chapterContentDecoded') || 
                            document.querySelector('#chapterContent') || 
                            document.querySelector('.chapter-content') ||
                            document.querySelector('.post-content');
            if (!container) return "";
            let result = extractTextFromNode(container);
            return result.replace(/\\n{3,}/g, '\\n\\n').trim();
            """

            for i, c_link in enumerate(chapter_links, 1):
                if not self.is_running: break
                
                driver = self._nav(c_link)
                self._sleep(2, 3.5)
                
                if not self.wait_for_cloudflare(): continue
                driver = self.get_valid_driver()
                
                is_locked = False
                try:
                    if "Ố Dè" in driver.page_source or driver.find_elements(By.ID, "passwordInput"):
                        is_locked = True
                except Exception:
                    _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

                if is_locked:
                    self.log(f"   - 🔐 Chương {i} bị khóa. Đang thử các mật khẩu đã biết...")
                    success = False
                    
                    candidates = []
                    if last_successful_password: candidates.append(last_successful_password)
                    candidates.extend([p for p in known_passwords if p != last_successful_password])
                    
                    for pwd in candidates:
                        if self.try_trichtinhlau_password(pwd):
                            self.log(f"   - ✅ Đã mở khóa bằng password: {pwd}")
                            last_successful_password = pwd
                            success = True
                            self._sleep(2)
                            break
                    
                    if not success:
                        self.log(f"   - 🛑 Không có mật khẩu đúng cho chương {i}. Dừng cào truyện này.")
                        has_invalid_password = True
                        break

                try:
                    raw_content = driver.execute_script(decode_js) or ""
                    
                    if not raw_content or len(raw_content) < 50:
                        try:
                            raw_content = driver.find_element(By.ID, "chapterContent").text
                        except Exception:
                            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

                    found_pwds = self.extract_trichtinhlau_password(raw_content)
                    if found_pwds: 
                        for p in found_pwds:
                            if p not in known_passwords:
                                known_passwords.add(p)
                                self.log(f"   - 🔑 Tìm thấy mật khẩu tiềm năng ở chương {i}: {p}")
                    
                    chapters_data.append((f"Chương {i}", raw_content))
                except Exception as e:
                    self.log(f"   - ⚠️ Lỗi chương {i}: {str(e)[:50]}")
                    chapters_data.append((f"Chương {i}", "[Lỗi tải nội dung]"))

                if i % 10 == 0 or i == len(chapter_links):
                    self.log(f"   ↳ Đã tải {i}/{len(chapter_links)} chương")
                
                self._set_progress(((idx - 1) / total) + ((i / len(chapter_links)) * (1 / total)))

            if chapters_data:
                if has_invalid_password:
                    self.log(f"   - ⏭️ Bỏ qua truyện '{story_name}' do không tìm thấy mật khẩu đúng ở một số chương.")
                elif not self.is_running:
                    self.log(f"⏹ Đã dừng — '{story_name}' chưa hoàn tất, các chương đã tải chưa được lưu nên lần sau sẽ tải lại từ đầu.")
                else:
                    if self.create_epub(story_name, chapters_data, dest_dir, cover_data):
                        self.save_history(url)
                        self.queue_remove(url)

        except Exception as e:
            self.log(f"   - ❌ Lỗi xử lý Trích Tinh Lâu: {str(e)[:100]}")

    def extract_trichtinhlau_password(self, content):
        if not content: return []
        patterns = [
            r'(?:mật khẩu|pass|password|pw)(?:\s+(?:của\s+)?(?:các\s+)?(?:[\w\d\s]+\s+)?chương\s+(?:truyện|sau))?\s*(?:là)?\s*[:：]?\s*([^\s<.,;:!?/]+)',
            r'(?:mật khẩu|pass|password|pw)\s+là\s+([^\s<.,;:!?\s/]+)'
        ]
        results = []
        for p in patterns:
            matches = re.findall(p, content, re.IGNORECASE)
            for m in matches:
                pwd = m.strip().rstrip('.,;:!?')
                if pwd and 1 <= len(pwd) < 25:
                    results.append(pwd)
        return list(set(results))

    def try_trichtinhlau_password(self, password):
        try:
            driver = self.get_valid_driver()
            p_inputs = driver.find_elements(By.CSS_SELECTOR, "#passwordInput, input[type='password']")
            if not p_inputs: return False
            p_input = p_inputs[0]
            
            p_input.clear()
            p_input.send_keys(str(password))
            self._sleep(0.5)
            
            try:
                submit_btn = driver.find_element(By.CSS_SELECTOR, "button.btn-info, button[type='submit'], .btn-primary")
                driver.execute_script("arguments[0].click();", submit_btn)
            except Exception:
                p_input.send_keys("\n")
            
            self._sleep(3)
            
            try:
                content_div = driver.find_element(By.ID, "chapterContent")
                if content_div.is_displayed() and len(content_div.text.strip()) > 100:
                    return True
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
            
            if not driver.find_elements(By.ID, "passwordInput") and "Ố Dè" not in driver.page_source:
                return True
                
            return False
        except Exception:
            return False
