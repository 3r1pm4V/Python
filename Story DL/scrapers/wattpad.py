"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import customtkinter as ctk

import re
from html import escape as _html_escape
from pathlib import Path
from typing import List, Tuple, Optional, Dict


from app_core.constants import (
    WATTPAD_API_BASE, WATTPAD_WEB_BASE,
    WATTPAD_HEADERS, WATTPAD_IMPERSONATE, WATTPAD_CHAPTER_DELAY,
    WATTPAD_STATUS_SELECTOR, WATTPAD_TAGS_SELECTOR,
    WATTPAD_TAG_PAGE_DELAY, WATTPAD_TAG_PAGE_SIZE, WATTPAD_TAG_MAX_PAGES, WATTPAD_TAG_MISMATCH_ABORT,
)
from app_core.text_utils import (
    find_dam_my_tag, find_blocked_tag, extract_wattpad_story_ids, has_required_tag, parse_required_tags,
    parse_wattpad_story_page, parse_wattpad_list_url,
)


class WattpadMixin:
    def _setup_wattpad_tab(self) -> None:
        tab = self.tab_wattpad
        tab.grid_columnconfigure(0, weight=1)

        info = ctk.CTkLabel(
            tab,
            text=(
                "Tải truyện Wattpad qua API ẩn — không cần browser, không bị Cloudflare chặn.\n"
                "Nhập URL truyện (https://www.wattpad.com/story/123456789-ten-truyen)\n"
                "hoặc URL tag / tìm kiếm để tải hàng loạt\n"
                "(https://www.wattpad.com/stories/hvan  hoặc  https://www.wattpad.com/search/hvan)"
            ),
            text_color=self.TEXT_MUTED,
            justify="center",
            font=("Inter", 11)
        )
        info.grid(row=0, column=0, pady=(20, 10), padx=20)

        ctk.CTkLabel(tab, text="URL Truyện Wattpad:", font=("Inter", 11, "bold")).grid(
            row=1, column=0, sticky="w", padx=30, pady=(8, 0)
        )
        self.entry_wattpad_url = ctk.CTkEntry(
            tab,
            placeholder_text="https://www.wattpad.com/story/123456789-ten-truyen",
            height=42,
            font=("Inter", 11),
            fg_color=self.BG_INPUT,
            border_width=1,
            border_color=self.BORDER_COLOR
        )
        self.entry_wattpad_url.grid(row=2, column=0, sticky="ew", padx=30, pady=6)

        range_frame = ctk.CTkFrame(tab, fg_color="transparent")
        range_frame.grid(row=3, column=0, pady=8)

        ctk.CTkLabel(range_frame, text="Chapter bắt đầu:").pack(side="left", padx=5)
        self.wattpad_chap_start = ctk.CTkEntry(range_frame, width=65, justify="center", fg_color=self.BG_INPUT, border_width=1, border_color=self.BORDER_COLOR)
        self.wattpad_chap_start.insert(0, "1")
        self.wattpad_chap_start.pack(side="left", padx=5)

        ctk.CTkLabel(range_frame, text="Chapter kết thúc (0 = tất cả):").pack(side="left", padx=5)
        self.wattpad_chap_end = ctk.CTkEntry(range_frame, width=65, justify="center", fg_color=self.BG_INPUT, border_width=1, border_color=self.BORDER_COLOR)
        self.wattpad_chap_end.insert(0, "0")
        self.wattpad_chap_end.pack(side="left", padx=5)

        ctk.CTkLabel(range_frame, text="Số truyện tối đa khi tải theo tag (0 = tất cả):").pack(side="left", padx=(15, 5))
        self.wattpad_tag_limit = ctk.CTkEntry(range_frame, width=65, justify="center", fg_color=self.BG_INPUT, border_width=1, border_color=self.BORDER_COLOR)
        self.wattpad_tag_limit.insert(0, "50")
        self.wattpad_tag_limit.pack(side="left", padx=5)

        proxy_label_frame = ctk.CTkFrame(tab, fg_color="transparent")
        proxy_label_frame.grid(row=4, column=0, sticky="ew", padx=30, pady=(10, 0))
        ctk.CTkLabel(
            proxy_label_frame,
            text="Proxy (GoodbyeDPI / SOCKS5 / HTTP):",
            font=("Inter", 10, "bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            proxy_label_frame,
            text="  tự detect từ Windows nếu để trống",
            font=("Inter", 9),
            text_color=self.TEXT_MUTED,
        ).pack(side="left")

        proxy_input_frame = ctk.CTkFrame(tab, fg_color="transparent")
        proxy_input_frame.grid(row=5, column=0, sticky="ew", padx=30, pady=3)
        proxy_input_frame.grid_columnconfigure(0, weight=1)

        self.entry_wattpad_proxy = ctk.CTkEntry(
            proxy_input_frame,
            placeholder_text="socks5://127.0.0.1:1080  hoặc  http://127.0.0.1:8080  (để trống = auto-detect)",
            height=38,
            font=("Inter", 10),
            fg_color=self.BG_INPUT,
            border_width=1,
            border_color=self.BORDER_COLOR
        )
        self.entry_wattpad_proxy.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            proxy_input_frame,
            text="Detect",
            width=80,
            height=38,
            fg_color=self.BG_INPUT,
            hover_color=self.BORDER_COLOR,
            font=("Inter", 10, "bold"),
            command=self._wattpad_detect_proxy_ui,
        ).grid(row=0, column=1)

        ctk.CTkLabel(
            tab,
            text="Cookie (tuỳ chọn — cần cho truyện 18+ hoặc yêu cầu đăng nhập):",
            font=("Inter", 10),
            text_color=self.TEXT_MUTED,
        ).grid(row=6, column=0, sticky="w", padx=30, pady=(10, 0))
        self.entry_wattpad_cookie = ctk.CTkEntry(
            tab,
            placeholder_text="Dán chuỗi cookie từ browser vào đây (để trống nếu không cần)",
            height=38,
            font=("Inter", 10),
            fg_color=self.BG_INPUT,
            border_width=1,
            border_color=self.BORDER_COLOR
        )
        self.entry_wattpad_cookie.grid(row=7, column=0, sticky="ew", padx=30, pady=4)

        tag_frame = ctk.CTkFrame(tab, fg_color="transparent")
        tag_frame.grid(row=9, column=0, sticky="ew", padx=30, pady=(4, 0))
        ctk.CTkLabel(tag_frame, text="Tag bắt buộc (khi tải theo tag; cách nhau bằng dấu phẩy, có 1 trong số đó là được; để trống = tag trong URL):",
                     font=("Inter", 10), text_color=self.TEXT_MUTED).pack(anchor="w")
        self.entry_wattpad_required_tags = ctk.CTkEntry(
            tag_frame, placeholder_text="hvan, caoh", height=34, font=("Inter", 10),
            fg_color=self.BG_INPUT, border_width=1, border_color=self.BORDER_COLOR,
        )
        self.entry_wattpad_required_tags.pack(fill="x", pady=3)

        self.wattpad_status_label = ctk.CTkLabel(
            tab, text="", font=("Inter", 11), text_color=self.TEAL_PRIMARY
        )
        self.wattpad_status_label.grid(row=8, column=0, pady=4)

        ctk.CTkButton(
            tab,
            text="⬇️  TẢI TRUYỆN WATTPAD",
            height=44,
            font=("Inter", 13, "bold"),
            fg_color=self.TEAL_PRIMARY,
            hover_color=self.TEAL_HOVER,
            command=lambda: self.start_thread("wattpad"),
        ).grid(row=10, column=0, padx=30, pady=20, sticky="ew")

    def _wattpad_detect_system_proxy(self) -> Optional[str]:
        try:
            import winreg
            reg_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
                proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if not proxy_enable:
                    return None
                proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                if not proxy_server:
                    return None
                if "=" in proxy_server:
                    for scheme in ("https", "http"):
                        for part in proxy_server.split(";"):
                            if part.strip().startswith(scheme + "="):
                                addr = part.strip().split("=", 1)[1]
                                return f"http://{addr}"
                    addr = proxy_server.split(";")[0].split("=")[-1]
                    return f"http://{addr}"
                else:
                    return f"http://{proxy_server}"
        except Exception:
            return None

    def _wattpad_detect_proxy_ui(self) -> None:
        proxy = self._wattpad_detect_system_proxy()
        self.entry_wattpad_proxy.delete(0, "end")
        if proxy:
            self.entry_wattpad_proxy.insert(0, proxy)
            self.log(f"🔍 [Wattpad] Phát hiện system proxy: {proxy}")
        else:
            self.log("🔍 [Wattpad] Không tìm thấy system proxy trong Windows registry.")

    def _wattpad_parse_story_id(self, url: str) -> Optional[str]:
        m = re.search(r"/story/(\d+)", url)
        if m:
            return m.group(1)
        m = re.search(r"wattpad\.com/(\d+)-", url)
        if m:
            return m.group(1)
        return None

    def _wattpad_build_session(self):
        try:
            self._ensure_curl_cffi()
        except ImportError as exc:
            self.log(f"❌ {exc}")
            raise

        from curl_cffi import requests as cffi_requests
        session = cffi_requests.Session(impersonate=WATTPAD_IMPERSONATE)
        session.headers.update(WATTPAD_HEADERS)

        proxy_url: Optional[str] = self.entry_wattpad_proxy.get().strip() or None
        if not proxy_url:
            proxy_url = self._wattpad_detect_system_proxy()
            if proxy_url:
                self.log(f"🌐 [Wattpad] Auto-detect proxy: {proxy_url}")
        if proxy_url:
            session.proxies = {"http": proxy_url, "https": proxy_url}
        else:
            self.log("🌐 [Wattpad] Không có proxy — kết nối trực tiếp.")

        raw_cookie = self.entry_wattpad_cookie.get().strip()
        if raw_cookie:
            for pair in raw_cookie.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, _, v = pair.partition("=")
                    session.cookies.set(k.strip(), v.strip(), domain=".wattpad.com")

        return session

    def _wattpad_fetch_story_meta(self, session, story_id: str) -> Optional[Dict]:
        base_url = f"{WATTPAD_API_BASE}/stories/{story_id}"
        params = {
            "fields": (
                "id,title,url,cover,description,"
                "user(name,username),"
                "numParts,completed,"
                "mainCategory,categories,tags,"
                "parts(id,title,url,text_url)"
            ),
            "limit": 50,
            "offset": 0,
        }
        try:
            resp = session.get(base_url, params=params, timeout=20)
            resp.raise_for_status()
            meta = resp.json()
        except Exception as e:
            self.log(f"   ❌ Lỗi lấy metadata: {str(e)[:100]}")
            return None

        total_parts: int = meta.get("numParts", 0)
        fetched_parts: List[Dict] = meta.get("parts", [])

        while len(fetched_parts) < total_parts and self.is_running:
            try:
                # offset = số part ĐÃ nhận (không cố định 50): nếu API trả ít hơn 50 ở lần đầu thì không bị hụt chương
                offset = len(fetched_parts)
                p_params = {
                    "fields": "parts(id,title,url,text_url)",
                    "limit": 50,
                    "offset": offset,
                }
                r = session.get(base_url, params=p_params, timeout=20)
                r.raise_for_status()
                batch = r.json().get("parts", [])
                if not batch:
                    break
                fetched_parts.extend(batch)
                self.log(f"   📄 Đang lấy danh sách chapter: {len(fetched_parts)}/{total_parts}")
            except Exception as e:
                self.log(f"   ⚠️ Lỗi paginate parts offset={offset}: {str(e)[:80]}")
                break

        meta["parts"] = fetched_parts
        return meta

    def _wattpad_fetch_chapter_html(self, session, text_url: str) -> str:
        try:
            resp = session.get(text_url, timeout=20)
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "").lower()

            if "application/json" in content_type:
                data = resp.json()
                if isinstance(data, dict):
                    return (
                        data.get("text")
                        or (data.get("data") or {}).get("text")
                        or ""
                    )
                return ""
            else:
                text = resp.text.strip()
                if text and not text.startswith("<"):
                    text = f"<p>{_html_escape(text)}</p>"
                return text

        except Exception as e:
            self.log(f"   ⚠️ Lỗi lấy chapter ({type(e).__name__}): {str(e)[:100]}")
            return ""

    def _wattpad_fetch_cover(self, session, cover_url: str) -> Optional[bytes]:
        if not cover_url:
            return None
        try:
            resp = session.get(cover_url, timeout=15)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            self.log(f"   ⚠️ Không tải được ảnh bìa: {str(e)[:60]}")
            return None

    # ------------------------------------------------------------------
    # Bộ lọc: Hoàn thành + loại Đam mỹ/BL
    # ------------------------------------------------------------------
    def _wattpad_fetch_story_page(self, session, story_id: str) -> Tuple[Optional[bool], List[str]]:
        """Dự phòng: đọc trạng thái + tag từ HTML trang truyện bằng selector trong constants.

        Returns:
            ``(completed, tags)``; ``(None, [])`` nếu tải/đọc trang thất bại.
        """
        try:
            resp = session.get(
                f"{WATTPAD_WEB_BASE}/story/{story_id}",
                headers={"Accept": "text/html,application/xhtml+xml"},
                timeout=20,
            )
            resp.raise_for_status()
            return parse_wattpad_story_page(resp.text, WATTPAD_STATUS_SELECTOR, WATTPAD_TAGS_SELECTOR)
        except Exception as e:
            self.log(f"   ⚠️ Không đọc được trang truyện để kiểm tra bộ lọc: {str(e)[:80]}")
            return None, []

    def _wattpad_filter_reason(
        self, session, story_id: str, meta: Dict, required_tags: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Trả về lý do cần BỎ QUA truyện, hoặc ``None`` nếu truyện hợp lệ.

        Thứ tự: (0) phải có ít nhất 1 tag trong ``required_tags`` (nếu truyền vào), (1) tag Đam mỹ/BL,
        (2) "Chỉ tải Hoàn thành" nếu được bật.
        Nguồn dữ liệu chính là API (``tags``/``completed``); nếu API thiếu thì đọc HTML trang truyện
        bằng ``WATTPAD_STATUS_SELECTOR`` / ``WATTPAD_TAGS_SELECTOR``.
        """
        api_tags: List[str] = [str(t) for t in (meta.get("tags") or [])]
        completed: Optional[bool] = meta.get("completed") if isinstance(meta.get("completed"), bool) else None

        need_completed = bool(self.completed_only_var.get())
        page_tags: List[str] = []
        # Chỉ tốn thêm 1 request khi API thiếu dữ liệu cần thiết.
        if not api_tags or (need_completed and completed is None):
            page_completed, page_tags = self._wattpad_fetch_story_page(session, story_id)
            if completed is None:
                completed = page_completed

        category_texts: List[str] = []
        main_cat = meta.get("mainCategory") or {}
        if isinstance(main_cat, dict):
            category_texts.append(str(main_cat.get("name", "")))
        elif isinstance(main_cat, str):
            category_texts.append(main_cat)
        for cat in (meta.get("categories") or []):
            category_texts.append(str(cat.get("name", "")) if isinstance(cat, dict) else str(cat))

        if required_tags and not has_required_tag(api_tags + page_tags, required_tags):
            self._wattpad_last_skip_kind = "tag_mismatch"
            return f"không có tag bắt buộc ({', '.join(required_tags)})"

        blocked = find_blocked_tag(api_tags + page_tags) or find_dam_my_tag(category_texts)
        if blocked is not None:
            self._wattpad_last_skip_kind = "blocked"
            return f"có tag Đam mỹ/BL ('{blocked}')"

        if need_completed:
            if completed is None:
                return "không xác định được trạng thái (đang bật 'Chỉ tải Hoàn thành')"
            if not completed:
                return "chưa Hoàn Thành"
        return None

    # ------------------------------------------------------------------
    # Tải theo tag: https://www.wattpad.com/stories/<tag>
    # ------------------------------------------------------------------
    def _wattpad_tag_ids_from_api(self, session, tag: str, offset: int, kind: str = "tag") -> Optional[List[str]]:
        """Lấy 1 trang ID truyện qua API (``kind``: ``"tag"`` hoặc ``"search"``); ``None`` nếu API lỗi."""
        try:
            resp = session.get(
                f"{WATTPAD_API_BASE}/stories",
                params={("tags" if kind == "tag" else "query"): tag, "fields": "stories(id)", "limit": WATTPAD_TAG_PAGE_SIZE, "offset": offset},
                timeout=20,
            )
            resp.raise_for_status()
            return [str(s["id"]) for s in (resp.json().get("stories") or []) if isinstance(s, dict) and s.get("id")]
        except Exception as e:
            self.log(f"   ⚠️ API danh sách tag lỗi (offset={offset}): {str(e)[:80]}")
            return None

    def _wattpad_tag_ids_from_html(self, session, tag: str, offset: int, kind: str = "tag") -> List[str]:
        """Dự phòng: quét link ``/story/<id>`` từ HTML trang tag (``?offset=``)."""
        from urllib.parse import quote
        section = "stories" if kind == "tag" else "search"
        url = f"{WATTPAD_WEB_BASE}/{section}/{quote(tag)}" + (f"?offset={offset}" if offset else "")
        try:
            resp = session.get(url, headers={"Accept": "text/html,application/xhtml+xml"}, timeout=20)
            resp.raise_for_status()
            return extract_wattpad_story_ids(resp.text)
        except Exception as e:
            self.log(f"   ⚠️ Không tải được trang tag (offset={offset}): {str(e)[:80]}")
            return []

    def _wattpad_collect_tag_story_ids(self, session, tag: str, limit: int, kind: str = "tag") -> List[str]:
        """Thu thập ID truyện của tag, không trùng, tối đa ``limit`` (0 = không giới hạn).

        Thử API trước, lỗi thì chuyển sang quét HTML. Dừng khi một trang không có ID mới
        (phân trang hết hoặc server bỏ qua offset) hoặc chạm ``WATTPAD_TAG_MAX_PAGES``.
        Độ phức tạp: O(P) request, P = số trang.
        """
        ids: Dict[str, None] = {}
        use_api = True
        for page in range(WATTPAD_TAG_MAX_PAGES):
            if not self.is_running or (limit and len(ids) >= limit):
                break
            offset = page * WATTPAD_TAG_PAGE_SIZE
            batch: Optional[List[str]] = self._wattpad_tag_ids_from_api(session, tag, offset, kind) if use_api else None
            if batch is None:
                use_api = False
                batch = self._wattpad_tag_ids_from_html(session, tag, offset, kind)
            new_ids = [i for i in batch if i not in ids]
            if not new_ids:
                break
            for i in new_ids:
                ids.setdefault(i, None)
            self.log(f"   📚 Đã thu thập {len(ids)} truyện của {'tag' if kind == 'tag' else 'từ khoá'} '{tag}'")
            self._sleep(*WATTPAD_TAG_PAGE_DELAY)
        result = list(ids)
        return result[:limit] if limit else result

    def process_wattpad_tag(self, tag_url: str, dest_dir: Path) -> None:
        """Tải hàng loạt truyện từ URL tag (``/stories/<tag>``) hoặc tìm kiếm (``/search/<từ khoá>``).

        Mỗi truyện đều qua bộ lọc: tag bắt buộc, Đam mỹ/BL, Hoàn thành.
        """
        parsed = parse_wattpad_list_url(tag_url)
        if not parsed:
            self.log("❌ URL không hợp lệ. Ví dụ: https://www.wattpad.com/stories/hvan "
                     "hoặc https://www.wattpad.com/search/hvan")
            return
        kind, tag = parsed
        try:
            limit = max(0, int(self.wattpad_tag_limit.get().strip() or "0"))
        except ValueError:
            self.log("⚠️ 'Số truyện tối đa' không hợp lệ — dùng 50.")
            limit = 50

        required = parse_required_tags(self.entry_wattpad_required_tags.get()) or [tag]
        session = self._wattpad_build_session()
        self.log(f"🏷️ {'Tag' if kind == 'tag' else 'Tìm kiếm'}: {tag} | tag bắt buộc: {', '.join(required)} | tối đa: {limit or 'tất cả'} | "
                 f"chỉ Hoàn Thành: {'có' if self.completed_only_var.get() else 'không'}")
        story_ids = self._wattpad_collect_tag_story_ids(session, tag, limit, kind)
        if not story_ids:
            self.log("⚠️ Không lấy được truyện nào từ URL này. Dừng.")
            return

        known_blocked = [sid for sid in story_ids
                         if self.normalize_url(f"{WATTPAD_WEB_BASE}/story/{sid}") in self.blocked_urls]
        if known_blocked:
            skip = set(known_blocked)
            story_ids = [sid for sid in story_ids if sid not in skip]
            self.log(f"🚫 Bỏ qua ngay {len(known_blocked)} truyện đã bị loại (BL) ở các lần chạy trước — "
                     "không gọi API lại (xem blocked.txt).")
            if not story_ids:
                self.log("✨ Không còn truyện nào để xử lý.")
                return

        total = len(story_ids)
        self.log(f"📋 Sẽ xử lý {total} truyện.")
        mismatched = 0          # số truyện liên tiếp không có tag bắt buộc
        matched_any = False
        for n, sid in enumerate(story_ids, 1):
            if not self.is_running:
                self.log("⏹ Đã dừng theo yêu cầu.")
                return
            story_url = f"{WATTPAD_WEB_BASE}/story/{sid}"
            self.log(f"━━ [{n}/{total}] {story_url}")
            if not self.overwrite_var.get() and self.normalize_url(story_url) in self.downloaded_urls:
                self.log("⏭️ Bỏ qua: đã có trong lịch sử.")
                continue
            try:
                self._wattpad_last_skip_kind = None
                self.process_wattpad_story(story_url, dest_dir, session=session, required_tags=required)
                if self._wattpad_last_skip_kind == "tag_mismatch":
                    mismatched += 1
                else:
                    mismatched = 0
                    matched_any = True
                if not matched_any and mismatched >= WATTPAD_TAG_MISMATCH_ABORT:
                    self.log(f"⛔ {mismatched} truyện đầu tiên đều KHÔNG có tag '{', '.join(required)}' — "
                             "nguồn danh sách có vẻ sai tag. Dừng để tránh tải nhầm (gửi log để chỉnh lại).")
                    return
            except Exception as exc:  # 1 truyện lỗi không làm hỏng cả lượt
                self.log(f"   ❌ Lỗi, bỏ qua truyện này: {str(exc)[:100]}")
            self._sleep(*WATTPAD_TAG_PAGE_DELAY)

    def process_wattpad_story(
        self, raw_url: str, dest_dir: Path, session=None, required_tags: Optional[List[str]] = None,
    ) -> None:
        """Tải 1 truyện Wattpad thành EPUB (sau khi qua bộ lọc Hoàn thành / Đam mỹ).

        Args:
            raw_url: URL truyện.
            dest_dir: thư mục đầu ra.
            session: session dùng chung (chế độ tải theo tag); ``None`` thì tự tạo.
            required_tags: truyện phải có ít nhất 1 tag trong danh sách này (``None`` = không ràng buộc).
        """
        story_id = self._wattpad_parse_story_id(raw_url)
        if not story_id:
            self.log("❌ Không nhận dạng được Story ID từ URL này.")
            return

        self.log(f"🔍 Story ID: {story_id}")
        if session is None:
            session = self._wattpad_build_session()

        self.log("📡 Đang gọi Wattpad API để lấy thông tin truyện...")
        meta = self._wattpad_fetch_story_meta(session, story_id)
        if not meta:
            self.log("❌ Không lấy được metadata. Dừng.")
            return

        story_title: str = meta.get("title", f"wattpad_{story_id}").strip()
        author_name: str = (meta.get("user") or {}).get("name", "Unknown")
        cover_url: str   = meta.get("cover", "")
        all_parts: List[Dict] = meta.get("parts", [])
        is_completed: bool = meta.get("completed", False)

        self._wattpad_last_skip_kind = None
        story_url = f"{WATTPAD_WEB_BASE}/story/{story_id}"
        if self._is_blocked_title(story_title, "🚫"):
            self.save_blocked(story_url, "tiêu đề BL", story_title)
            self._wattpad_last_skip_kind = "blocked"
            return
        reason = self._wattpad_filter_reason(session, story_id, meta, required_tags)
        if reason:
            self.log(f"🚫 Bỏ qua '{story_title}': {reason}")
            if self._wattpad_last_skip_kind == "blocked":  # chỉ lưu lý do vĩnh viễn (BL), không lưu "chưa hoàn thành"
                self.save_blocked(story_url, reason, story_title)
            return

        dest_dir_path = Path(self.entry_path.get())
        if not self.overwrite_var.get() and self.check_epub_exists(dest_dir_path, story_title):
            self.log(f"⏭️ Bỏ qua: {story_title} (File đã có, bật 'Overwrite Existing' để tải lại)")
            return

        self.log(f"📖 Truyện  : {story_title}")
        self.log(f"✍️  Tác giả : {author_name}")
        self.log(f"📑 Chapters: {len(all_parts)} ({'Hoàn thành' if is_completed else 'Đang ra'})")

        if not all_parts:
            self.log("⚠️ Truyện không có chapter nào hoặc bị khoá. Dừng.")
            return

        try:
            chap_start = max(1, int(self.wattpad_chap_start.get()))
            chap_end   = int(self.wattpad_chap_end.get())
        except ValueError:
            chap_start, chap_end = 1, 0

        if chap_end <= 0 or chap_end > len(all_parts):
            chap_end = len(all_parts)

        selected_parts = all_parts[chap_start - 1 : chap_end]
        self.log(f"🎯 Sẽ tải: chapter {chap_start} → {chap_end} ({len(selected_parts)} chương)")

        chapters_data: List[Tuple[str, str]] = []
        self.queue_add(raw_url)

        for idx, part in enumerate(selected_parts, 1):
            if not self.is_running:
                self.log("⏹ Đã dừng theo yêu cầu.")
                return

            chap_title: str = part.get("title", f"Chapter {idx}")
            text_url_obj = part.get("text_url") or {}
            text_url: str = text_url_obj.get("text", "")

            self._set_progress(idx / len(selected_parts))
            self.log(f"   [{idx}/{len(selected_parts)}] {chap_title}")

            if not text_url:
                self.log("   ⚠️ Không có text_url cho chapter này (bị khoá?)")
                chapters_data.append((chap_title, "<p><em>[Nội dung bị khoá hoặc không có]</em></p>"))
            else:
                html_content = self._wattpad_fetch_chapter_html(session, text_url)
                chapters_data.append((chap_title, html_content if html_content else "<p><em>[Không tải được nội dung]</em></p>"))

            self._sleep(*WATTPAD_CHAPTER_DELAY)

        if not chapters_data:
            self.log("⚠️ Không có chapter nào được tải. EPUB sẽ không được tạo.")
            return

        if not self.is_running:
            self.log(f"⏹ Đã dừng — '{story_title}' chưa hoàn tất, các chương đã tải chưa được lưu nên lần sau sẽ tải lại từ đầu.")
            return

        self.log("🖼️  Đang tải ảnh bìa...")
        cover_data: Optional[bytes] = self._wattpad_fetch_cover(session, cover_url)

        self.log("📦 Đang tạo file EPUB...")
        if self.create_epub(story_title, chapters_data, dest_dir, cover_data, author=author_name):
            self.save_history(raw_url)
            self.queue_remove(raw_url)
            self.log(f"✅ Hoàn tất: {story_title}")
