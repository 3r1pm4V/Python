"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import logging

import re
import json
import threading
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from urllib.parse import urljoin, urlparse


from app_core.constants import (
    TOKEN_FILE, MND_API_BASE, INVALID_FS_CHARS_RE, logger,
)


_dbg = logging.getLogger(__name__)


class KhoSachMndMixin:
    def _load_mnd_tokens(self) -> None:
        if TOKEN_FILE.exists():
            try:
                data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
                self.mnd_access_token = data.get("access_token")
                self.mnd_refresh_token = data.get("refresh_token")
                if self.mnd_access_token:
                    self.mnd_session.headers.update({"Authorization": f"Bearer {self.mnd_access_token}"})
            except Exception as e:
                logger.warning(f"Không thể load MND token: {e}")

    def _save_mnd_tokens(self) -> None:
        try:
            TOKEN_FILE.write_text(json.dumps({
                "access_token": self.mnd_access_token,
                "refresh_token": self.mnd_refresh_token
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Không thể ghi MND token: {e}")

    def mnd_login(self, username: str, password: str) -> bool:
        try:
            resp = self.mnd_session.post(
                f"{MND_API_BASE}/auth/login",
                data={"username": username, "password": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=(5, 12)
            )
            if resp.status_code == 200:
                data = resp.json()
                self.mnd_access_token = data.get("access_token")
                self.mnd_refresh_token = data.get("refresh_token")
                self.mnd_session.headers.update({"Authorization": f"Bearer {self.mnd_access_token}"})
                self._save_mnd_tokens()
                self.log("✅ [MND API] Đăng nhập tài khoản MND thành công!")
                return True
            else:
                self.log(f"❌ [MND API] Đăng nhập thất bại ({resp.status_code}): {resp.text[:100]}")
                return False
        except Exception as e:
            self.log(f"❌ [MND API] Lỗi kết nối đăng nhập: {e}")
            return False

    def _mnd_do_refresh_token(self) -> bool:
        if not self.mnd_refresh_token:
            return False
        try:
            resp = self.mnd_session.post(
                f"{MND_API_BASE}/auth/refresh",
                params={"refresh_token": self.mnd_refresh_token},
                timeout=(5, 12)
            )
            if resp.status_code == 200:
                data = resp.json()
                self.mnd_access_token = data.get("access_token")
                self.mnd_refresh_token = data.get("refresh_token")
                self.mnd_session.headers.update({"Authorization": f"Bearer {self.mnd_access_token}"})
                self._save_mnd_tokens()
                return True
            self.log(f"   ⚠️ [MND API] Làm mới token thất bại (HTTP {resp.status_code}) — có thể cần đăng nhập lại.")
        except Exception as exc:
            _dbg.debug("Lỗi làm mới token MND", exc_info=True)
            self.log(f"   ⚠️ [MND API] Lỗi làm mới token: {type(exc).__name__}: {str(exc)[:80]}")
        return False

    def mnd_api_request(self, method: str, endpoint: str, **kwargs) -> Optional[Any]:
        url = f"{MND_API_BASE}{endpoint}"
        try:
            resp = self.mnd_session.request(method, url, timeout=(5, 10), **kwargs)
            if resp.status_code == 401:
                if self._mnd_do_refresh_token():
                    resp = self.mnd_session.request(method, url, timeout=(5, 10), **kwargs)
                else:
                    self.log(f"   ⚠️ [MND API] {method} {endpoint} → 401 (token hết hạn/không hợp lệ).")
                    return None
            if resp.status_code != 200:
                self.log(f"   ⚠️ [MND API] {method} {endpoint} → HTTP {resp.status_code}")
                return None
            return resp.json()
        except Exception as exc:
            _dbg.debug("Lỗi gọi MND API %s", endpoint, exc_info=True)
            self.log(f"   ⚠️ [MND API] {method} {endpoint} lỗi: {type(exc).__name__}: {str(exc)[:80]}")
            return None

    def mnd_get_download_url_api(self, book_id: int, format_str: str = "epub") -> Optional[str]:
        url = f"{MND_API_BASE}/files/book/{book_id}/{format_str}"
        try:
            resp = self.mnd_session.get(url, allow_redirects=False, timeout=(5, 12))
            if resp.status_code == 302:
                return resp.headers.get("Location")
            elif resp.status_code == 200:
                return url
            self.log(f"   ⚠️ [MND API] Link tải sách {book_id} → HTTP {resp.status_code} (có thể cần đăng nhập VIP).")
        except Exception as e:
            logger.warning(f"Lỗi MND API Download Link: {e}")
            self.log(f"   ⚠️ [MND API] Lỗi lấy link tải sách {book_id}: {type(e).__name__}: {str(e)[:80]}")
        return None

    def _get_khosachmnd_genre_total_and_links(self, genre_url: str) -> Tuple[Optional[int], List[Dict[str, str]]]:
        cat_match = re.search(r'/(?:categories|category|tag|new)/(?:new/)?(\d+)', genre_url)
        if not cat_match:
            cat_match = re.search(r'id=(\d+)', genre_url)
            
        books_list = []
        if cat_match:
            cat_id = cat_match.group(1)
            page_match = re.search(r'[?&]page=(\d+)', genre_url)
            page = int(page_match.group(1)) if page_match else 1
            
            self.log(f"   📡 [MND API] Đang gọi API lấy danh sách trang {page} (ID: {cat_id})...")
            
            endpoints_to_try = [
                (f"/categories/{cat_id}/books", {"page": page, "per_page": 60}),
                ("/books/", {"page": page, "per_page": 60, "sort_param": "new", "category_id": cat_id}),
                ("/books/", {"page": page, "per_page": 60, "sort_param": "new", "tag_id": cat_id}),
            ]  # KHÔNG thêm endpoint /books/ trần: nó trả sách của MỌI thể loại, sai danh sách
            
            for ep, params in endpoints_to_try:
                raw_res = self.mnd_api_request("GET", ep, params=params)
                if raw_res:
                    if isinstance(raw_res, list) and raw_res:
                        books_list = raw_res
                        break
                    elif isinstance(raw_res, dict):
                        for key in ["books", "data", "items", "results"]:
                            if key in raw_res and isinstance(raw_res[key], list) and raw_res[key]:
                                books_list = raw_res[key]
                                break
                        if books_list:
                            break

        if books_list:
            items = []
            for b in books_list:
                if isinstance(b, dict):
                    b_id = b.get("id") or b.get("_id") or b.get("book_id")
                    b_title = b.get("title") or b.get("name") or ""
                    
                    b_author = ""
                    author_field = b.get("author") or b.get("authors") or b.get("writer")
                    if isinstance(author_field, str):
                        b_author = author_field.strip()
                    elif isinstance(author_field, list) and author_field:
                        b_author = ", ".join([str(a.get("name", "") if isinstance(a, dict) else a) for a in author_field]).strip()
                    elif isinstance(author_field, dict):
                        b_author = str(author_field.get("name", "")).strip()

                    if b_id and b_title:
                        items.append({
                            "url": f"https://khosach.mnd.vn/book/{b_id}",
                            "title": str(b_title).strip(),
                            "author": b_author
                        })
            if items:
                self.log(f"   ✅ [MND API] Lấy thành công {len(items)} sách qua API.")
                return len(items), items

        self.log("   ⚠️ [MND API] Không lấy được qua API, chuyển sang Selenium Cào DOM trực tiếp...")
        try:
            driver = self.get_valid_driver()
            driver.get(genre_url)
            if not self.wait_for_cloudflare():
                return None, []
            driver = self.get_valid_driver()  # wait_for_cloudflare có thể đã đổi sang Chrome thật

            for _ in range(3):
                driver.execute_script("window.scrollBy(0, 1000);")
                self._sleep(1)

            items = driver.execute_script("""
                let results = [];
                let seen = new Set();
                let cards = document.querySelectorAll("div#root div.grid div.flex.flex-col.group");
                
                if (cards.length > 0) {
                    cards.forEach(card => {
                        let a_tags = card.querySelectorAll("a[href*='/book/']");
                        if (a_tags.length > 0) {
                            let href = a_tags[0].getAttribute('href') || a_tags[0].href;
                            if (href) {
                                if (href.startsWith('/')) href = 'https://khosach.mnd.vn' + href;
                                if (!seen.has(href)) {
                                    seen.add(href);
                                    let title = '';
                                    let author = '';
                                    let h3 = card.querySelector("h3");
                                    if (h3 && h3.innerText) title = h3.innerText.trim();
                                    if (!title) {
                                        let img = card.querySelector("img");
                                        if (img && img.alt) title = img.alt.trim();
                                    }
                                    let authEl = card.querySelector(".text-gray-500, p, span");
                                    if (authEl && authEl.innerText) author = authEl.innerText.trim();

                                    results.push({
                                        url: href,
                                        title: title || href.split('/').pop(),
                                        author: author
                                    });
                                }
                            }
                        }
                    });
                }
                return results;
            """) or []

            if items:
                self.log(f"   ✅ [Selenium DOM] Tìm thấy {len(items)} truyện qua Web DOM!")

            return len(items), items
        except Exception as exc:
            self.log(f"   ⚠️ Lỗi cào DOM Kho Sách MND: {str(exc)[:80]}")
            return None, []

    def process_khosachmnd_story(self, url: str, idx: int, total: int, dest_dir: Path, cache=None, pre_title: str = "", pre_author: str = "") -> None:
        try:
            book_id_match = re.search(r'/book/(\d+)', url)
            book_id = int(book_id_match.group(1)) if book_id_match else None
            
            if pre_title and self._is_blocked_title(pre_title, f"[{idx}/{total}]"):
                return

            story_name = pre_title if pre_title else f"mnd_{book_id if book_id else url.split('/')[-1]}"
            story_author = pre_author
            download_url = None

            if book_id:
                download_url = self.mnd_get_download_url_api(book_id, "epub")

            if story_author:
                clean_author = re.sub(r'^(Tác giả|Author):\s*', '', story_author, flags=re.IGNORECASE).strip()
                final_filename = f"{story_name} - {clean_author}"
            else:
                final_filename = story_name

            safe_filename = INVALID_FS_CHARS_RE.sub('_', final_filename)

            if not self.overwrite_var.get() and self.is_story_already_downloaded(url, dest_dir, safe_filename, cache):
                self.log(f"[{idx}/{total}] Bỏ qua: {safe_filename} (File đã có)")
                self.save_history(url, safe_filename)
                return

            if download_url:
                if not download_url.startswith("http"):
                    download_url = urljoin("https://khosach.mnd.vn", download_url)
                
                self.queue_add(url)
                self.log(f"[{idx}/{total}] ⬇️ Đang tải: {safe_filename}")
                
                save_path = dest_dir / f"{safe_filename}.epub"
                try:
                    # Link tải thường chuyển hướng sang host khác (CDN/S3 presigned): KHÔNG gửi Bearer token
                    # của MND sang đó (lộ token, và S3 từ chối khi có 2 cơ chế xác thực).
                    host = urlparse(download_url).netloc.lower()
                    hdrs = None if host.endswith("khosach.mnd.vn") else {"Authorization": None}
                    resp = self.mnd_session.get(download_url, stream=True, timeout=(5, 60), headers=hdrs)
                    if resp.status_code == 200:
                        # Ghi qua .part + kiểm tra EPUB hợp lệ: không để file HTML/dở dang bị coi là "đã tải"
                        if self._save_stream_as_epub(resp, save_path):
                            self.log(f"   ✅ Đã tải thành công: {safe_filename}")
                            self.save_history(url, safe_filename)
                            self.queue_remove(url)
                        else:
                            self.log(f"   ❌ File tải về không phải EPUB hợp lệ, đã huỷ: {safe_filename}")
                    else:
                        actual_filename = self.download_general(download_url, dest_dir, safe_filename)
                        if actual_filename:
                            self.save_history(url, actual_filename)
                            self.queue_remove(url)
                except Exception as dl_err:
                    self.log(f"   ❌ Lỗi tải file: {str(dl_err)[:60]}")
            else:
                self.log(f"   ❌ Không tìm thấy link EPUB cho {safe_filename}")

        except Exception as e:
            self.log(f"   ❌ Lỗi xử lý Khosach MND ({url}): {str(e)[:100]}")

    def _btn_mnd_login_action(self):
        u = getattr(self, 'entry_mnd_user', None)
        p = getattr(self, 'entry_mnd_pass', None)
        if not u or not p: return
        user_val = u.get().strip()
        pass_val = p.get().strip()
        if not user_val or not pass_val:
            self.log("❌ Vui lòng nhập Username và Password MND.")
            return
        threading.Thread(target=self.mnd_login, args=(user_val, pass_val), daemon=True).start()
