"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import logging

import re
import random
import threading
import concurrent.futures
from pathlib import Path
from typing import List, Optional, Dict
from urllib.parse import urlparse, unquote

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app_core.net_utils import is_cloudflare_challenge, build_genre_page_url
from app_core.text_utils import pick_epub_link, parse_wattpad_list_url, find_blocked_title
from app_core.genre_parsers import (
    parse_dtv_genre, parse_trichtinhlau_genre, parse_monkeyd_genre, parse_catalog_genre,
    METRUYENCHU_STORY_RE, TANGTHUVIEN_STORY_RE,
)
from app_core.constants import (
    MAX_CONCURRENT_DOWNLOADS,
    BASE_URL,
    INVALID_FS_CHARS_RE,
)


_dbg = logging.getLogger(__name__)


class OrchestratorMixin:
    def _sleep(self, seconds: float, high: Optional[float] = None) -> bool:
        """Ngủ ``seconds`` giây (hoặc ngẫu nhiên trong [seconds, high]) nhưng thức dậy NGAY khi bấm STOP.

        Trả ``True`` nếu ngủ đủ, ``False`` nếu bị STOP cắt ngang (hoặc app đang không chạy).
        Chỉ dùng trong luồng worker; KHÔNG dùng trong vòng lặp thăm dò mà không kiểm tra
        ``is_running`` (khi đã STOP hàm trả về ngay nên vòng lặp sẽ chạy bận).
        """
        if high is not None:
            seconds = random.uniform(seconds, high)
        return not self._stop_event.wait(max(0.0, seconds))

    def _mode_url(self, attr: str) -> str:
        """Đọc URL từ ô nhập ``attr``; không có thì dùng ô URL chung. '' nếu không có ô nào."""
        w = getattr(self, attr, None)
        if w is None:
            w = getattr(self, "entry_combined_url", None)
        return w.get().strip() if w is not None else ""

    def run_process(self, mode: str, run_gen: int = 0) -> None:
        self.log("🚀 Bắt đầu quá trình...")
        self.after(0, lambda: self.tabview.set("📋 Activity Logs"))
        
        # Khởi tạo trước để tránh NameError trong khối finally nếu hàm return sớm
        khosachmnd_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
        khosachmnd_futures: List[concurrent.futures.Future] = []
        truyenfull_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
        truyenfull_futures: List[concurrent.futures.Future] = []

        try:
            dest_dir = Path(self.entry_path.get())
            dest_dir.mkdir(parents=True, exist_ok=True)

            self.log("📂 Đang quét cache thư mục đầu ra (bao gồm thư mục con)...")
            files_cache = {f.name.lower() for f in dest_dir.rglob("*.epub")}
            self.log(f"📊 Đã cache {len(files_cache)} file.")
            
            target_items = []
            if mode == "genre":
                base_genre = self._mode_url('entry_genre_url')
                if not base_genre: return self.log("❌ Vui lòng nhập URL thể loại.")
                try:
                    start = int(self.page_start.get())
                    end = int(self.page_end.get())
                except Exception:
                    start, end = 1, 1
                
                for p in range(start, end + 1):
                    if not self.is_running: break
                    url = build_genre_page_url(base_genre, p)
                    target_items.extend(self.get_book_links_with_titles(url))
            elif mode == "monkeyd":
                url = self._mode_url('entry_monkeyd_url')
                if not url: return self.log("❌ Enter a MonkeyD URL")
                if "/the-loai/" in url or "page=" in url:
                    try:
                        start = int(self.page_start.get())
                        end = int(self.page_end.get())
                    except Exception:
                        start, end = 1, 1
                    for p in range(start, end + 1):
                        if not self.is_running: break
                        if p > 1:
                            p_url = f"{url.split('?')[0]}?page={p}"
                            if "monkeydd.com" in p_url:
                                p_url = p_url.replace("www.", "")
                        else:
                            p_url = url
                        target_items.extend(self.get_book_links_with_titles(p_url))
                else: target_items = [{'url': url, 'title': '', 'author': ''}]
            elif mode == "hako":
                url = self._mode_url('entry_hako_url')
                if not url: return self.log("❌ Vui lòng nhập URL truyện Hako.")
                target_items = [{'url': url, 'title': '', 'author': ''}]
            elif mode == "khosachmnd":
                url = self._mode_url('entry_khosachmnd_url')
                if not url: return self.log("❌ Vui lòng nhập URL Kho Sách MND")
                if any(k in url for k in ["/categories/", "/category/", "/tag/"]):
                    try:
                        start = int(self.khosachmnd_page_start.get())
                        end = int(self.khosachmnd_page_end.get())
                    except Exception:
                        start, end = 1, 1
                    
                    for p in range(start, end + 1):
                        if not self.is_running: break
                        connector = "&" if "?" in url else "?"
                        p_url = f"{url}{connector}page={p}" if p > 1 else url
                        target_items.extend(self.get_book_links_with_titles(p_url))
                else:
                    target_items = [{'url': url, 'title': '', 'author': ''}]
            else:
                url = self._mode_url('entry_single_url')
                if not url: return self.log("❌ Vui lòng nhập URL truyện.")
                target_items = [{'url': url, 'title': '', 'author': ''}]

            seen_urls = set()
            unique_items = []
            for item in target_items:
                norm_u = self.normalize_url(item['url'])
                if norm_u and norm_u not in seen_urls:
                    seen_urls.add(norm_u)
                    unique_items.append(item)
            
            if not self.overwrite_var.get():
                initial_count = len(unique_items)
                filtered_items = []
                for item in unique_items:
                    norm_u = self.normalize_url(item['url'])
                    in_history = norm_u in self.downloaded_urls
                    
                    if in_history:
                        pre_t = item.get('title', '')
                        if not pre_t:
                            book_id = item['url'].rstrip("/").split("/")[-1].replace(".html", "")
                            pre_t = book_id
                        
                        file_exists_on_disk = self.is_story_already_downloaded(
                            item['url'], dest_dir, pre_t, cache=files_cache
                        )
                        if not file_exists_on_disk:
                            self.log(f"⚠️ URL có trong lịch sử nhưng mất file trên ổ đĩa, tiến hành tải lại: {pre_t}")
                            filtered_items.append(item)
                        else:
                            continue
                    else:
                        filtered_items.append(item)

                skipped = initial_count - len(filtered_items)
                unique_items = filtered_items
                if skipped > 0:
                    self.log(f"♻️ Tự động lọc: Bỏ qua {skipped} truyện đã tải (theo lịch sử và còn file).")

            total = len(unique_items)
            if total == 0:
                self.log("✨ Không có truyện mới nào cần tải.")
                return

            self.log(f"📋 Thực tế cần xử lý: {total} truyện.")

            khosachmnd_executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS)
            truyenfull_executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS)

            for i, item in enumerate(unique_items, 1):
                if not self.is_running: break
                
                try:
                    link = item['url']
                    pre_title = item.get('title', '')
                    pre_author = item.get('author', '')
                    self._set_progress(i / total)
                
                    domain = urlparse(link).netloc.lower()
                    if "khosach.mnd.vn" in domain:
                        khosachmnd_futures.append(khosachmnd_executor.submit(
                            self.process_khosachmnd_story, link, i, total, dest_dir, files_cache, pre_title, pre_author
                        ))
                        continue
                    elif "trichtinhlau.com" in domain:
                        self.process_trichtinhlau_story(link, i, total, dest_dir)
                        continue
                    elif "monkeydd.com" in domain or "monkeyd.net.vn" in domain:
                        if not self.overwrite_var.get() and self.normalize_url(link) in self.downloaded_urls:
                            continue

                        self._nav(link)
                        self._sleep(1)
                        if not self.wait_for_cloudflare(): continue
                    
                        m_genres = self.extract_monkeyd_genres()
                        m_genres_lower = [sg.lower() for sg in m_genres]
                    
                        if any("đam mỹ" in g for g in m_genres_lower):
                            self.log(f"[{i}/{total}] Bỏ qua: Phát hiện Đam mỹ (MonkeyD).")
                            continue

                        selected = [g for g, v in self.monkeyd_genre_checkboxes.items() if v.get()]
                        if selected:
                            has_match = any(g in m_genres_lower for g in selected)
                            if (self.monkeyd_filter_mode.get() == "include" and not has_match) or \
                               (self.monkeyd_filter_mode.get() == "exclude" and has_match):
                                self.log(f"[{i}/{total}] Bỏ qua: Thể loại không khớp.")
                                continue
                    
                        if self.completed_only_var.get() and not self.is_monkeyd_completed():
                            self.log(f"[{i}/{total}] Bỏ qua: Chưa hoàn thành.")
                            continue
                        
                        self.process_monkeyd_story(link, i, total, dest_dir, cache=files_cache)
                        continue
                    elif any(d in domain for d in ["docln.net", "docln.sbs", "ln.hako.vn"]):
                        self.process_hako_story(link, i, total, dest_dir, cache=files_cache)
                        continue
                    elif "truyenfull.live" in domain or "truyenfull.vn" in domain:
                        truyenfull_futures.append(truyenfull_executor.submit(
                            self.process_truyenfull_story, link, i, total, dest_dir, files_cache
                        ))
                        continue
                    elif "metruyenchu.com" in domain or "metruyencv.com" in domain:
                        self.process_metruyenchu_story(link, i, total, dest_dir, cache=files_cache)
                        continue
                    elif "tangthuvien.vn" in domain:
                        self.process_tangthuvien_story(link, i, total, dest_dir, cache=files_cache)
                        continue

                    dtv_title, dtv_author = self.get_dtv_story_info(link)
                
                    if dtv_title:
                        if dtv_author:
                            clean_author = re.sub(r'^(Tác giả|Author):\s*', '', dtv_author, flags=re.IGNORECASE).strip()
                            formatted_book_name = f"{dtv_title} - {clean_author}"
                        else:
                            formatted_book_name = dtv_title
                    else:
                        raw_slug = link.rstrip("/").split("/")[-1].replace(".html", "")
                        formatted_book_name = unquote(raw_slug)

                    safe_book_name = INVALID_FS_CHARS_RE.sub('_', formatted_book_name).strip()

                    if self._is_blocked_title(formatted_book_name, f"[{i}/{total}]"):
                        continue

                    if not self.overwrite_var.get() and self.is_story_already_downloaded(link, dest_dir, safe_book_name, cache=files_cache):
                        self.log(f"[{i}/{total}] Bỏ qua: {safe_book_name} (File đã có)")
                        self.save_history(link, safe_book_name)
                        continue

                    self.log(f"[{i}/{total}] Đang xử lý: {safe_book_name}")

                    if not self.check_book_filters(link):
                        continue
                
                    epub_url = self.get_epub_link(link)
                
                    if epub_url:
                        self.queue_add(link)
                        actual_filename = self.download_general(epub_url, dest_dir, safe_book_name)
                        if actual_filename:
                            self.save_history(link, actual_filename)
                            self.queue_remove(link)
                    else:
                        self.log("   - ⚠️ Không tìm thấy link EPUB")
                
                    self._sleep(0.3, 0.8)
                except Exception as exc:
                    # 1 truyện lỗi (timeout, driver chết...) chỉ bỏ qua truyện đó, KHÔNG dừng cả lượt tải
                    self.log(f"[{i}/{total}] ❌ Lỗi, bỏ qua: {str(exc)[:100]}")
                
        except Exception as e:
            self.log(f"❌ LỖI: {str(e)[:100]}")
        finally:
            pending = [f for f in khosachmnd_futures if not f.done()]
            pending += [f for f in truyenfull_futures if not f.done()]
            if pending:
                self.log(f"⏳ Đang chờ {len(pending)} tải song song hoàn tất...")

            for f in khosachmnd_futures:
                try:
                    f.result()
                except Exception as exc:
                    self.log(f"   ❌ Lỗi luồng tải Kho Sách MND: {str(exc)[:100]}")
            if khosachmnd_executor is not None:
                khosachmnd_executor.shutdown(wait=True)

            for f in truyenfull_futures:
                try:
                    f.result()
                except Exception as exc:
                    self.log(f"   ❌ Lỗi luồng tải Truyện Full: {str(exc)[:100]}")
            if truyenfull_executor is not None:
                truyenfull_executor.shutdown(wait=True)

            self.log("🧹 Đang đóng trình duyệt...")
            self._restart_driver()
            self._finish_run(run_gen)
            self._set_progress(1)
            self.log("🏁 Hoàn tất.")

    def start_thread(self, mode: str) -> None:
        if self._worker is not None and self._worker.is_alive():
            self.log("⚠️ Đang có tác vụ chạy (hoặc đang dừng). Nhấn STOP và đợi tác vụ cũ kết thúc.")
            return
        loader = getattr(self, "_genre_load_thread", None)
        if loader is not None and loader.is_alive():
            self.log("⚠️ Đang nạp thể loại MonkeyD (đang dùng trình duyệt). Đợi xong rồi hãy bấm tải.")
            return
        self._save_config()
        self._run_generation += 1
        my_gen = self._run_generation
        # Bật cờ chạy ngay ở luồng chính (không phải trong worker): nếu để trong worker, bấm STOP
        # ngay sau khi start có thể bị worker ghi đè lại thành "đang chạy".
        self.is_running = True
        if mode == "genre_copy":
            target, args = self._run_genre_copy_wrapper, (my_gen,)
        elif mode == "wattpad":
            target, args = self._run_wattpad_wrapper, (my_gen,)
        else:
            target, args = self.run_process, (mode, my_gen)
        self._worker = threading.Thread(target=target, args=args, daemon=True)
        self._worker.start()

    def _finish_run(self, my_gen: int) -> None:
        if my_gen == self._run_generation:
            self.is_running = False

    def _run_wattpad_wrapper(self, my_gen: int = 0) -> None:
        raw_url = self.entry_wattpad_url.get().strip()
        if not raw_url:
            self.log("❌ [Wattpad] Vui lòng nhập URL truyện.")
            self._finish_run(my_gen)
            return

        self.after(0, self.progress.set, 0)
        self.after(0, lambda: self.tabview.set("📋 Activity Logs"))
        self.log("🚀 [Wattpad] Bắt đầu tải (không cần browser)...")

        try:
            dest_dir = Path(self.entry_path.get())
            dest_dir.mkdir(parents=True, exist_ok=True)
            if parse_wattpad_list_url(raw_url):
                self.process_wattpad_tag(raw_url, dest_dir)
            else:
                self.process_wattpad_story(raw_url, dest_dir)
        except Exception as exc:
            self.log(f"❌ [Wattpad] Lỗi không mong muốn: {str(exc)[:120]}")
        finally:
            self._finish_run(my_gen)
            self.after(0, self.progress.set, 1)
            self.log("🏁 [Wattpad] Kết thúc.")

    def _run_genre_copy_wrapper(self, my_gen: int = 0) -> None:
        self.after(0, self.progress.set, 0)
        self.after(0, lambda: self.tabview.set("📋 Activity Logs"))
        self.log("🚀 [Genre Copy] Bắt đầu...")
        try:
            self.run_genre_copy()
        except Exception as exc:
            self.log(f"❌ [Genre Copy] Lỗi không mong muốn: {str(exc)[:100]}")
        finally:
            self._restart_driver()
            self._finish_run(my_gen)
            self.after(0, self.progress.set, 1)

    def stop_process(self) -> None:
        self._stop_event.set()
        self.log("⏹ Đang yêu cầu dừng...")

    def check_book_filters(self, book_url) -> bool:
        try:
            html_content = ""
            try:
                resp = self.http_session.get(book_url, timeout=(5, 10))
                if resp.status_code == 200 and not is_cloudflare_challenge(resp.status_code, resp.text):
                    html_content = resp.text
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

            if not html_content:
                driver = self.get_valid_driver()
                if self.normalize_url(driver.current_url) != self.normalize_url(book_url):
                    driver.get(book_url)
                    if not self.wait_for_cloudflare(): return False
                    driver = self.get_valid_driver()  # có thể đã đổi sang Chrome thật
                html_content = driver.page_source

            soup = BeautifulSoup(html_content, "html.parser")
            
            genre_texts = []
            for row in soup.select("table tr, .thongtin-sach tr"):
                row_text = row.get_text().lower()
                if any(k in row_text for k in ["thể loại", "từ khóa", "tags"]):
                    genre_texts.append(row_text)

            for tag in soup.select(".thongtin-sach a, table a, .tags a"):
                genre_texts.append(tag.get_text().lower())

            combined_genre_info = " ".join(genre_texts)

            if "đam mỹ" in combined_genre_info or "dam my" in combined_genre_info:
                self.log("   - Bỏ qua: Thể loại/Từ khóa chứa 'Đam mỹ'.")
                return False

            if self.completed_only_var.get():
                is_completed = False
                status_text = ""
                
                for row in soup.select("table tr, .thongtin-sach tr"):
                    row_text = row.get_text().lower()
                    if "tình trạng" in row_text or "trạng thái" in row_text:
                        status_text = row_text
                        break

                info_box = soup.select_one(".thongtin-sach")
                if "hoàn thành" in status_text or (info_box and "hoàn thành" in info_box.get_text().lower()):
                    is_completed = True
                
                if not is_completed:
                    self.log("   - Bỏ qua: Truyện chưa hoàn thành.")
                    return False

            return True
        except Exception as e:
            self.log(f"   - Lỗi lọc truyện: {str(e)[:50]}")
            return True

    def _fetch_genre_html(self, genre_url: str, *, site_key: str, use_browser_first: bool = False) -> str:
        """Lấy HTML trang danh sách: requests trước (nhanh), trượt thì mở trình duyệt (qua Cloudflare)."""
        if not use_browser_first:
            try:
                resp = self._net_get_with_retry(self.http_session, genre_url, timeout=(5, 15), label=f"{site_key}-genre")
                text = resp.text if resp.status_code == 200 else ""
                if text and not is_cloudflare_challenge(resp.status_code, text):
                    return text
            except Exception as exc:
                self.log(f"   ⚠️ Lỗi quét nhanh: {str(exc)[:50]}")

        if not self.is_running:
            return ""
        try:
            driver = self.get_valid_driver()
            driver.get(genre_url)
        except Exception as exc:
            self.log(f"⚠️ Lỗi truy cập trang: {str(exc)[:50]}")
            return ""
        if not self.wait_for_cloudflare():
            return ""
        # wait_for_cloudflare có thể đã đổi sang Chrome thật -> bỏ tham chiếu driver cũ (đã đóng)
        driver = self.get_valid_driver()
        if "monkeydd.com" in genre_url:
            try:
                WebDriverWait(driver, self._wdwait()).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".page-content"))
                )
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
        else:
            self._sleep(1)
        try:
            return driver.page_source or ""
        except Exception as exc:
            self.log(f"⚠️ Không đọc được nội dung trang: {str(exc)[:50]}")
            return ""

    def _is_blocked_title(self, title: str, label: str = "") -> bool:
        """``True`` (và ghi log) nếu tiêu đề chứa từ khoá BL: [BL], đm, dm, boylove, boyxboy...

        Dùng chung cho mọi site: bước lọc danh sách thể loại và bước kiểm tra từng truyện
        (để chặn cả khi dán link truyện đơn / danh sách không có tiêu đề).
        """
        kw = find_blocked_title(title or "")
        if kw is None:
            return False
        self.log(f"{label + ' ' if label else ''}Bỏ qua: tiêu đề chứa từ khoá BL '{kw}' — {title.strip()[:80]}")
        return True

    def _drop_blocked_title_items(self, items: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Loại các truyện có tiêu đề BL khỏi danh sách quét. Thiếu tiêu đề thì xét slug của URL."""
        kept: List[Dict[str, str]] = []
        dropped = 0
        for it in items:
            slug = unquote((it.get("url") or "").rstrip("/").split("/")[-1].replace(".html", ""))
            probe = it.get("title") or slug.replace("-", " ").replace("_", " ")
            if find_blocked_title(probe) is not None:
                dropped += 1
                self.log(f"   🚫 Loại (tiêu đề BL): {probe.strip()[:80]}")
            else:
                kept.append(it)
        if dropped:
            self.log(f"   🚫 Đã loại {dropped} truyện có từ khoá BL trong tiêu đề.")
        return kept

    def get_book_links_with_titles(self, genre_url: str) -> List[Dict[str, str]]:
        """Quét 1 trang thể loại rồi loại truyện có tiêu đề BL (đm, dm, bl, boylove, boyxboy...)."""
        return self._drop_blocked_title_items(self._scan_genre_page(genre_url))

    def _scan_genre_page(self, genre_url: str) -> List[Dict[str, str]]:
        """Danh sách truyện của MỘT trang thể loại: [{'url', 'title', 'author'}], giữ thứ tự, không trùng.

        Tất cả site dùng chung 1 đường đi này (cả tab tải truyện lẫn tab Genre Copy),
        bản cũ mỗi nơi tự viết một kiểu nên lệch nhau và sai ở nhiều site.
        """
        self.log(f"Quét trang: {genre_url}")
        low = genre_url.lower()
        try:
            if "khosach.mnd.vn" in low:
                _, items = self._get_khosachmnd_genre_total_and_links(genre_url)
                return items
            if "truyenfull" in low:
                return self._get_truyenfull_genre_links_with_titles(genre_url)

            if "trichtinhlau.com" in low:
                html = self._fetch_genre_html(genre_url, site_key="trichtinhlau", use_browser_first=True)
                items = parse_trichtinhlau_genre(
                    html, genre_url, self._sel("trichtinhlau", "book_links") or None
                ) if html else []
            elif "monkeydd.com" in low:
                html = self._fetch_genre_html(genre_url, site_key="monkeyd", use_browser_first=True)
                items = parse_monkeyd_genre(html, genre_url, self._sel("monkeyd", "story_container")) if html else []
            elif "metruyenchu.com" in low or "metruyencv.com" in low:
                html = self._fetch_genre_html(genre_url, site_key="metruyenchu")
                items = parse_catalog_genre(
                    html, genre_url, METRUYENCHU_STORY_RE, self._sel("metruyenchu", "genre_book_links") or None
                ) if html else []
            elif "tangthuvien.vn" in low:
                html = self._fetch_genre_html(genre_url, site_key="tangthuvien")
                items = parse_catalog_genre(
                    html, genre_url, TANGTHUVIEN_STORY_RE, self._sel("tangthuvien", "genre_book_links") or None
                ) if html else []
            else:  # dtv-ebook
                html = self._fetch_genre_html(genre_url, site_key="dtv")
                items = parse_dtv_genre(html, genre_url, BASE_URL) if html else []

            if items:
                self.log(f"   ✅ Tìm thấy {len(items)} truyện ở trang này.")
            else:
                self.log("   ⚠️ Trang này không có truyện nào (hết trang, bị chặn, hoặc selector không còn khớp).")
            return items
        except Exception as exc:
            self.log(f"   ❌ Lỗi quét trang: {str(exc)[:50]}")
            return []

    def get_book_links(self, genre_url):
        return [it["url"] for it in self.get_book_links_with_titles(genre_url) if it.get("url")]

    def get_epub_link(self, book_url: str) -> Optional[str]:
        """Link tải EPUB của trang sách: thử HTML tĩnh (requests) trước, không có thì mở trình duyệt."""
        try:
            resp = self.http_session.get(book_url, timeout=(5, 10))
            if resp.status_code == 200 and not is_cloudflare_challenge(resp.status_code, resp.text):
                link = pick_epub_link(resp.text, book_url)
                if link:
                    return link
        except Exception:
            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

        # HTML tĩnh không có link (bị chặn, hoặc link chỉ hiện sau khi bấm tab Download) -> dùng trình duyệt
        try:
            driver = self.get_valid_driver()
            if self.normalize_url(driver.current_url) != self.normalize_url(book_url):
                driver = self._nav(book_url)
                self._sleep(1)
                if not self.wait_for_cloudflare(): return None
                driver = self.get_valid_driver()  # có thể đã đổi sang Chrome thật

            try:
                tabs = driver.find_elements(By.CSS_SELECTOR, "ul.nav-tabs > li > a")
                for t_btn in tabs:
                    if any(x in t_btn.text.upper() for x in ["DOWNLOAD", "TẢI VỀ", "TẢI TRUYỆN"]):
                        driver.execute_script("arguments[0].click();", t_btn)
                        self._sleep(0.8)
                        break
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
            html_content = driver.page_source
        except Exception as e:
            self.log(f"   - Lỗi tìm link EPUB: {str(e)[:50]}")
            return None

        try:
            return pick_epub_link(html_content, book_url)
        except Exception as e:
            self.log(f"   - Lỗi parse link EPUB: {str(e)[:50]}")
            return None

    def _wdwait(self) -> int:
        return int(self._selectors.get("webdriver_wait_timeout", 4))
