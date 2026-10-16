"""Main GUI window — composes all mixins into the final StoryLoaderGUI class."""
from __future__ import annotations

import logging

from requests.adapters import HTTPAdapter

import os
import time
import shutil
import threading
from pathlib import Path
from typing import List, Optional, Set, Dict, Any

import requests
import customtkinter as ctk
from tkinter import filedialog

# Monkey-patch uc.Chrome.__del__ + cấu hình logging nằm ở app_core.bootstrap (gọi từ main.py).
from app_core.constants import APP_VERSION, DEFAULT_OUTPUT_DIR
from app_core.net_utils import build_genre_page_url, DEFAULT_BYEDPI_PROXY, requests_proxies
from app_core.selector_check import detect_site, build_report
from app_core.text_utils import normalize_for_match, best_title_match

from app_core.driver_mixin import DriverMixin
from app_core.http_mixin import HttpMixin
from app_core.config_mixin import ConfigMixin
from app_core.history_queue_mixin import HistoryQueueMixin
from app_core.epub_builder_mixin import EpubBuilderMixin
from app_core.orchestrator_mixin import OrchestratorMixin

from scrapers.dtv import DtvMixin
from scrapers.monkeyd import MonkeydMixin
from scrapers.trichtinhlau import TrichTinhLauMixin
from scrapers.truyenfull import TruyenFullMixin
from scrapers.hako import HakoMixin
from scrapers.khosachmnd import KhoSachMndMixin
from scrapers.metruyenchu import MetruyenchuMixin
from scrapers.tangthuvien import TangThuVienMixin
from scrapers.wattpad import WattpadMixin


_dbg = logging.getLogger(__name__)


class StoryLoaderGUI(
    ctk.CTk,
    DriverMixin, HttpMixin, ConfigMixin, HistoryQueueMixin, EpubBuilderMixin, OrchestratorMixin,
    DtvMixin, MonkeydMixin, TrichTinhLauMixin, TruyenFullMixin, HakoMixin,
    KhoSachMndMixin, MetruyenchuMixin, TangThuVienMixin, WattpadMixin,
):
    """Cửa sổ chính của ứng dụng. Kế thừa toàn bộ mixin scraper + core logic.

    Lưu ý MRO: ctk.CTk phải đứng đầu để __init__ gọi đúng Tk constructor;
    các mixin không định nghĩa __init__ riêng nên không xung đột.
    """

    def __init__(self):
        super().__init__()

        self.title(f"Story Loader v{APP_VERSION}")

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = min(1000, screen_width - 100)
        window_height = min(900, screen_height - 100)
        self.geometry(f"{window_width}x{window_height}")
        self.minsize(900, 800)

        ctk.set_appearance_mode("dark")

        # --- MODERN 2026 ZINC DARK PALETTE ---
        self.BG_DARK       = "#09090B"  # Zinc 950 Deep Background
        self.BG_CARD       = "#121215"  # Card / Frame Background
        self.BG_INPUT      = "#18181B"  # Entry / Dropdown Background
        self.BORDER_COLOR  = "#27272A"  # 1px Subtle Border (Zinc 800)
        
        self.TEAL_PRIMARY  = "#0D9488"  # Emerald Teal Accent
        self.TEAL_HOVER    = "#115E59"  # Hover Color
        
        self.TEXT_PRIMARY  = "#FAFAFA"  # Crisp White Text
        self.TEXT_MUTED    = "#A1A1AA"  # Secondary Muted Gray
        self.ACCENT_ERROR  = "#DC2626"  # Soft Red

        self.configure(fg_color=self.BG_DARK)

        self._stop_event = threading.Event()
        self._stop_event.set()  # trạng thái ban đầu: KHÔNG chạy (is_running == False)
        self._worker: Optional[threading.Thread] = None
        self._run_generation = 0
        self._history_lock = threading.Lock()
        self._queue_lock = threading.Lock()

        self.driver = None
        self.downloaded_urls = self.load_history()
        self.blocked_urls = self.load_blocked()
        self.available_monkeyd_genres = []
        self.monkeyd_genre_checkboxes = {}

        self.http_session = self._build_pooled_session()

        self.mnd_session = requests.Session()
        mnd_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
        self.mnd_session.mount("https://", mnd_adapter)
        self.mnd_session.mount("http://", mnd_adapter)
        self.mnd_access_token: Optional[str] = None
        self.mnd_refresh_token: Optional[str] = None
        self._load_mnd_tokens()

        self._config: Dict[str, Any] = self._load_config()
        self._selectors: Dict[str, Any] = self._load_selectors()
        self._keyring_available: bool = self._check_keyring()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._setup_ui()
        self._restore_config()
        self._ensure_selectors_file()

    def on_closing(self):
        self._stop_event.set()
        self._save_config()
        self._restart_driver()
        self.destroy()
        os._exit(0)

    @property
    def is_running(self) -> bool:
        return not self._stop_event.is_set()

    @is_running.setter
    def is_running(self, value: bool) -> None:
        if value:
            self._stop_event.clear()
        else:
            self._stop_event.set()

    def _set_progress(self, value: float) -> None:
        """Cập nhật progress bar an toàn từ worker thread (đẩy về luồng Tk)."""
        self.after(0, self.progress.set, value)

    def _setup_ui(self):
        # 1. HEADER
        header = ctk.CTkFrame(self, fg_color=self.BG_CARD, height=80, corner_radius=0, border_width=1, border_color=self.BORDER_COLOR)
        header.pack(fill="x", side="top")
        
        title = ctk.CTkLabel(header, text="📖 STORY LOADER", font=("Inter", 24, "bold"), text_color=self.TEXT_PRIMARY)
        title.pack(pady=(15, 2))
        
        subtitle = ctk.CTkLabel(header, text="Multi-source Ebook Scraper & Downloader", font=("Inter", 11), text_color=self.TEXT_MUTED)
        subtitle.pack(pady=(0, 15))

        # 2. OUTPUT PATH
        path_frame = ctk.CTkFrame(self, fg_color=self.BG_CARD, corner_radius=10, border_width=1, border_color=self.BORDER_COLOR)
        path_frame.pack(fill="x", padx=20, pady=12)
        
        ctk.CTkLabel(path_frame, text="💾 Đường dẫn lưu:", font=("Inter", 11, "bold"), text_color=self.TEXT_PRIMARY).pack(side="left", padx=15, pady=12)
        
        self.entry_path = ctk.CTkEntry(path_frame, font=("Inter", 11), fg_color=self.BG_INPUT, border_width=1, border_color=self.BORDER_COLOR, height=36)
        self.entry_path.insert(0, str(DEFAULT_OUTPUT_DIR))
        self.entry_path.pack(side="left", fill="x", expand=True, padx=5, pady=12)
        
        ctk.CTkButton(path_frame, text="Browse", width=90, height=36, fg_color=self.TEAL_PRIMARY, hover_color=self.TEAL_HOVER, font=("Inter", 11, "bold"), command=self.browse_path).pack(side="left", padx=15, pady=12)

        # 3. MAIN TABVIEW
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=20, pady=5)

        self.tabview = ctk.CTkTabview(
            self.main_container, 
            fg_color=self.BG_CARD, 
            corner_radius=10,
            segmented_button_fg_color=self.BG_INPUT,
            segmented_button_selected_color=self.TEAL_PRIMARY,
            segmented_button_selected_hover_color=self.TEAL_HOVER,
            segmented_button_unselected_color=self.BG_INPUT,
            segmented_button_unselected_hover_color=self.BORDER_COLOR
        )
        self.tabview.pack(side="left", fill="both", expand=True)
        
        self.tab_download   = self.tabview.add("📥 Tải Truyện")
        self.tab_wattpad    = self.tabview.add("🧡 Wattpad")
        self.tab_genre_copy = self.tabview.add("🚚 Genre Copy")
        self.tab_logs       = self.tabview.add("📋 Activity Logs")

        # 4. SIDEBAR
        self.sidebar = ctk.CTkFrame(self.main_container, fg_color=self.BG_CARD, width=200, corner_radius=10, border_width=1, border_color=self.BORDER_COLOR)
        self.sidebar.pack(side="right", fill="y", padx=(10, 0))
        self._setup_sidebar()

        self._setup_combined_download_tab()
        self._setup_wattpad_tab()
        self._setup_genre_copy_tab()
        self._setup_logs_tab()

        # 5. OPTIONS CHECKBOXES
        options_frame = ctk.CTkFrame(self, fg_color="transparent")
        options_frame.pack(fill="x", padx=20, pady=8)

        self.headless_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(options_frame, text="Ẩn trình duyệt (Headless)", variable=self.headless_var, font=("Inter", 11), fg_color=self.TEAL_PRIMARY, hover_color=self.TEAL_HOVER).pack(side="left", padx=10)

        ctk.CTkLabel(options_frame, text="Proxy trichtinhlau (byedpi):", font=("Inter", 11)).pack(side="left", padx=(20, 4))
        self.entry_trichtinhlau_proxy = ctk.CTkEntry(options_frame, width=170, font=("Inter", 11),
                                                     placeholder_text="socks5://127.0.0.1:1080")
        self.entry_trichtinhlau_proxy.insert(0, DEFAULT_BYEDPI_PROXY)
        self.entry_trichtinhlau_proxy.pack(side="left", padx=4)

        self.overwrite_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(options_frame, text="Ghi đè file cũ", variable=self.overwrite_var, font=("Inter", 11), fg_color=self.TEAL_PRIMARY, hover_color=self.TEAL_HOVER).pack(side="left", padx=10)

        self.completed_only_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(options_frame, text="Chỉ tải truyện Hoàn thành", variable=self.completed_only_var, font=("Inter", 11), fg_color=self.TEAL_PRIMARY, hover_color=self.TEAL_HOVER).pack(side="left", padx=10)

        ctk.CTkLabel(options_frame, text="🚫 Tự động lọc Đam mỹ", font=("Inter", 11), text_color="#EF4444").pack(side="left", padx=10)

        # 6. PROGRESS BAR & BUTTON STOP
        self.progress = ctk.CTkProgressBar(self, height=10, corner_radius=5, progress_color=self.TEAL_PRIMARY, fg_color=self.BG_INPUT)
        self.progress.pack(fill="x", padx=20, pady=5)
        self.progress.set(0)

        self.btn_stop = ctk.CTkButton(self, text="STOP PROCESS", font=("Inter", 11, "bold"), height=38, fg_color=self.ACCENT_ERROR, hover_color="#991B1B", command=self.stop_process)
        self.btn_stop.pack(fill="x", padx=20, pady=(5, 15))

    def _setup_combined_download_tab(self):
        tab = self.tab_download
        tab.grid_columnconfigure(0, weight=1)

        controls_frame = ctk.CTkFrame(tab, fg_color=self.BG_INPUT, corner_radius=8, border_width=1, border_color=self.BORDER_COLOR)
        controls_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 10))
        controls_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(controls_frame, text="Nguồn website:", font=("Inter", 11, "bold")).grid(row=0, column=0, padx=15, pady=10, sticky="w")
        
        self.source_option_var = ctk.StringVar(value="Tự động nhận diện (Auto)")
        self.source_dropdown = ctk.CTkOptionMenu(
            controls_frame,
            values=[
                "Tự động nhận diện (Auto)",
                "Trang Tiếng Việt (MeTruyenChu, TangThuVien, TruyenFull...)",
                "dtv-ebook.com.vn",
                "monkeydd.com",
                "docln.net / Hako",
                "khosach.mnd.vn"
            ],
            variable=self.source_option_var,
            height=35,
            fg_color=self.BG_CARD,
            button_color=self.TEAL_PRIMARY,
            command=self._on_source_or_mode_change
        )
        self.source_dropdown.grid(row=0, column=1, padx=15, pady=10, sticky="ew")

        ctk.CTkLabel(controls_frame, text="Chế độ tải:", font=("Inter", 11, "bold")).grid(row=1, column=0, padx=15, pady=(0, 10), sticky="w")
        
        self.download_mode_var = ctk.StringVar(value="Chỉ 1 Truyện (Single)")
        mode_segmented = ctk.CTkSegmentedButton(
            controls_frame,
            values=["Chỉ 1 Truyện (Single)", "Cào Cả Thể Loại (Genre)"],
            variable=self.download_mode_var,
            selected_color=self.TEAL_PRIMARY,
            selected_hover_color=self.TEAL_HOVER,
            command=lambda m: self._on_source_or_mode_change()
        )
        mode_segmented.grid(row=1, column=1, padx=15, pady=(0, 10), sticky="ew")

        self.entry_combined_url = ctk.CTkEntry(
            tab, 
            placeholder_text="Dán đường dẫn (URL) truyện hoặc thể loại vào đây...", 
            height=42, 
            font=("Inter", 11),
            fg_color=self.BG_INPUT,
            border_width=1,
            border_color=self.BORDER_COLOR
        )
        self.entry_combined_url.grid(row=1, column=0, sticky="ew", padx=20, pady=10)

        self.dynamic_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self.dynamic_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=5)

        ctk.CTkButton(
            tab, 
            text="🚀 BẮT ĐẦU TẢI TRUYỆN", 
            height=44, 
            font=("Inter", 13, "bold"), 
            fg_color=self.TEAL_PRIMARY, 
            hover_color=self.TEAL_HOVER, 
            command=self._start_combined_download_action
        ).grid(row=3, column=0, padx=20, pady=15, sticky="ew")

        self._on_source_or_mode_change()

    def _on_source_or_mode_change(self, *args):
        for child in self.dynamic_frame.winfo_children():
            child.destroy()

        is_genre = "Thể Loại" in self.download_mode_var.get()
        selected_source = self.source_option_var.get()

        if is_genre or "khosach.mnd.vn" in selected_source:
            range_frame = ctk.CTkFrame(self.dynamic_frame, fg_color="transparent")
            range_frame.pack(pady=5)
            
            ctk.CTkLabel(range_frame, text="Trang bắt đầu:").pack(side="left", padx=5)
            self.page_start = ctk.CTkEntry(range_frame, width=60, justify="center", fg_color=self.BG_INPUT, border_width=1, border_color=self.BORDER_COLOR)
            self.page_start.insert(0, "1")
            self.page_start.pack(side="left", padx=5)
            
            ctk.CTkLabel(range_frame, text="Trang kết thúc:").pack(side="left", padx=5)
            self.page_end = ctk.CTkEntry(range_frame, width=60, justify="center", fg_color=self.BG_INPUT, border_width=1, border_color=self.BORDER_COLOR)
            self.page_end.insert(0, "1")
            self.page_end.pack(side="left", padx=5)

            if "khosach.mnd.vn" in selected_source:
                self.khosachmnd_page_start = self.page_start
                self.khosachmnd_page_end = self.page_end

        if "khosach.mnd.vn" in selected_source:
            auth_frame = ctk.CTkFrame(self.dynamic_frame, fg_color=self.BG_INPUT, corner_radius=6, border_width=1, border_color=self.BORDER_COLOR)
            auth_frame.pack(fill="x", pady=5)
            
            ctk.CTkLabel(auth_frame, text="🔑 Tài khoản KhoSách MND (Tùy chọn VIP):", font=("Inter", 10, "bold")).pack(anchor="w", padx=10, pady=(5, 2))
            input_subframe = ctk.CTkFrame(auth_frame, fg_color="transparent")
            input_subframe.pack(fill="x", padx=10, pady=(0, 5))
            
            self.entry_mnd_user = ctk.CTkEntry(input_subframe, placeholder_text="Username", height=30, font=("Inter", 10), fg_color=self.BG_CARD, border_width=1, border_color=self.BORDER_COLOR)
            self.entry_mnd_user.pack(side="left", fill="x", expand=True, padx=(0, 5))
            
            self.entry_mnd_pass = ctk.CTkEntry(input_subframe, placeholder_text="Password", show="*", height=30, font=("Inter", 10), fg_color=self.BG_CARD, border_width=1, border_color=self.BORDER_COLOR)
            self.entry_mnd_pass.pack(side="left", fill="x", expand=True, padx=(0, 5))
            
            ctk.CTkButton(
                input_subframe, 
                text="Đăng nhập API", 
                width=90, 
                height=30, 
                fg_color=self.TEAL_PRIMARY, 
                hover_color=self.TEAL_HOVER,
                font=("Inter", 10, "bold"),
                command=self._btn_mnd_login_action
            ).pack(side="left")

    def _start_combined_download_action(self):
        url = self.entry_combined_url.get().strip()
        if not url:
            self.log("❌ Vui lòng nhập đường dẫn (URL) truyện hoặc thể loại.")
            return

        is_genre = "Thể Loại" in self.download_mode_var.get() or "/the-loai/" in url or "/categories/" in url
        selected_source = self.source_option_var.get()

        if "monkeydd.com" in selected_source:
            self.entry_monkeyd_url = self.entry_combined_url
            mode = "monkeyd"
        elif "Hako" in selected_source:
            self.entry_hako_url = self.entry_combined_url
            mode = "hako"
        elif "khosach.mnd.vn" in selected_source:
            self.entry_khosachmnd_url = self.entry_combined_url
            mode = "khosachmnd"
        elif is_genre:
            self.entry_genre_url = self.entry_combined_url
            mode = "genre"
        else:
            self.entry_single_url = self.entry_combined_url
            mode = "single"

        self.start_thread(mode)

    def _setup_sidebar(self):
        ctk.CTkLabel(self.sidebar, text="🎯 MonkeyD Filters", font=("Inter", 12, "bold"), text_color=self.TEAL_PRIMARY).pack(pady=(15, 5))
        
        btn_load = ctk.CTkButton(self.sidebar, text="Load Genres", height=28, font=("Inter", 10), fg_color=self.BG_INPUT, hover_color=self.BORDER_COLOR, command=self.load_monkeyd_genres)
        btn_load.pack(padx=10, pady=5)

        self.monkeyd_filter_mode = ctk.StringVar(value="include")
        mode_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        mode_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkRadioButton(mode_frame, text="Incl", variable=self.monkeyd_filter_mode, value="include", font=("Inter", 9), fg_color=self.TEAL_PRIMARY).pack(side="left")
        ctk.CTkRadioButton(mode_frame, text="Excl", variable=self.monkeyd_filter_mode, value="exclude", font=("Inter", 9), fg_color=self.TEAL_PRIMARY).pack(side="left")

        self.monkeyd_genre_scroll = ctk.CTkScrollableFrame(self.sidebar, fg_color=self.BG_INPUT, height=400, border_width=1, border_color=self.BORDER_COLOR)
        self.monkeyd_genre_scroll.pack(fill="both", expand=True, padx=10, pady=10)

    def _setup_genre_copy_tab(self):
        tab = self.tab_genre_copy
        tab.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            tab,
            text=(
                "Quét tất cả truyện trong một trang thể loại,\n"
                "rồi copy các file EPUB đã tải ở thư mục cha vào thư mục con bạn chọn."
            ),
            text_color=self.TEXT_MUTED,
            justify="center",
            font=("Inter", 11)
        ).grid(row=0, column=0, pady=(20, 8))

        ctk.CTkLabel(tab, text="URL Thể Loại:", font=("Inter", 11, "bold")).grid(
            row=1, column=0, sticky="w", padx=30, pady=(8, 0)
        )
        self.entry_copy_genre_url = ctk.CTkEntry(
            tab,
            placeholder_text="https://dtv-ebook.com.vn/co-dai-511.html  hoặc  https://khosach.mnd.vn/category/new/6019",
            height=40,
            font=("Inter", 11),
            fg_color=self.BG_INPUT,
            border_width=1,
            border_color=self.BORDER_COLOR
        )
        self.entry_copy_genre_url.grid(row=2, column=0, sticky="ew", padx=30, pady=4)

        range_frame = ctk.CTkFrame(tab, fg_color="transparent")
        range_frame.grid(row=3, column=0, pady=6)
        ctk.CTkLabel(range_frame, text="Page Start:").pack(side="left", padx=5)
        self.copy_page_start = ctk.CTkEntry(range_frame, width=60, justify="center", fg_color=self.BG_INPUT, border_width=1, border_color=self.BORDER_COLOR)
        self.copy_page_start.insert(0, "1")
        self.copy_page_start.pack(side="left", padx=5)
        ctk.CTkLabel(range_frame, text="Page End:").pack(side="left", padx=5)
        self.copy_page_end = ctk.CTkEntry(range_frame, width=60, justify="center", fg_color=self.BG_INPUT, border_width=1, border_color=self.BORDER_COLOR)
        self.copy_page_end.insert(0, "1")
        self.copy_page_end.pack(side="left", padx=5)

        ctk.CTkLabel(tab, text="Thư mục đích (sub-folder):", font=("Inter", 11, "bold")).grid(
            row=4, column=0, sticky="w", padx=30, pady=(10, 0)
        )
        dest_frame = ctk.CTkFrame(tab, fg_color="transparent")
        dest_frame.grid(row=5, column=0, sticky="ew", padx=30, pady=4)
        dest_frame.grid_columnconfigure(0, weight=1)

        self.entry_copy_dest = ctk.CTkEntry(
            dest_frame,
            placeholder_text="Chọn thư mục con để copy vào...",
            height=40,
            font=("Inter", 11),
            fg_color=self.BG_INPUT,
            border_width=1,
            border_color=self.BORDER_COLOR
        )
        self.entry_copy_dest.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            dest_frame,
            text="Browse",
            width=100,
            fg_color=self.TEAL_PRIMARY,
            hover_color=self.TEAL_HOVER,
            font=("Inter", 11, "bold"),
            command=self._browse_copy_dest,
        ).grid(row=0, column=1)

        ctk.CTkLabel(
            tab,
            text="Thư mục nguồn (để trống = dùng Output Path ở trên):",
            font=("Inter", 10),
            text_color=self.TEXT_MUTED,
        ).grid(row=6, column=0, sticky="w", padx=30, pady=(10, 0))
        src_frame = ctk.CTkFrame(tab, fg_color="transparent")
        src_frame.grid(row=7, column=0, sticky="ew", padx=30, pady=4)
        src_frame.grid_columnconfigure(0, weight=1)

        self.entry_copy_src = ctk.CTkEntry(
            src_frame,
            placeholder_text="(Để trống để dùng Output Path)",
            height=40,
            font=("Inter", 11),
            fg_color=self.BG_INPUT,
            border_width=1,
            border_color=self.BORDER_COLOR
        )
        self.entry_copy_src.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            src_frame,
            text="Browse",
            width=100,
            fg_color=self.BG_INPUT,
            hover_color=self.BORDER_COLOR,
            font=("Inter", 11, "bold"),
            command=self._browse_copy_src,
        ).grid(row=0, column=1)

        mode_frame = ctk.CTkFrame(tab, fg_color="transparent")
        mode_frame.grid(row=8, column=0, pady=(4, 0))
        self.copy_mode_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            mode_frame,
            text="Copy (giữ file gốc) — bỏ tick để Move (xoá file gốc sau khi chuyển)",
            variable=self.copy_mode_var,
            font=("Inter", 10),
            fg_color=self.TEAL_PRIMARY,
            hover_color=self.TEAL_HOVER
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            tab,
            text="🚚 QUÉT & COPY / MOVE",
            height=44,
            font=("Inter", 13, "bold"),
            fg_color=self.TEAL_PRIMARY,
            hover_color=self.TEAL_HOVER,
            command=lambda: self.start_thread("genre_copy"),
        ).grid(row=9, column=0, padx=30, pady=20, sticky="ew")

    def _browse_copy_dest(self) -> None:
        path = filedialog.askdirectory(title="Chọn thư mục đích (sub-folder)")
        if path:
            self.entry_copy_dest.delete(0, "end")
            self.entry_copy_dest.insert(0, path)

    def _browse_copy_src(self) -> None:
        path = filedialog.askdirectory(title="Chọn thư mục nguồn chứa EPUB")
        if path:
            self.entry_copy_src.delete(0, "end")
            self.entry_copy_src.insert(0, path)

    def _normalize_for_match(self, text: str) -> str:
        return normalize_for_match(text)

    def _scrape_story_titles_from_genre(self, genre_url: str, start_page: int, end_page: int) -> List[str]:
        """Tên truyện của các trang start..end — dùng CHUNG đường quét với tab tải truyện."""
        titles: List[str] = []
        for page in range(start_page, end_page + 1):
            if not self.is_running:
                break
            url = build_genre_page_url(genre_url, page)
            self.log(f"   📄 Quét trang {page}: {url}")
            try:
                items = self.get_book_links_with_titles(url)
            except Exception as exc:
                self.log(f"   ❌ Lỗi quét trang {page}: {str(exc)[:60]}")
                continue
            if not items:
                self.log(f"   ⚠️ Trang {page} không có truyện — dừng sớm.")
                break
            for item in items:
                t = (item.get("title") or "").strip()
                if len(t) > 2:
                    titles.append(t)

        seen: Set[str] = set()
        unique: List[str] = []
        for t in titles:
            key = t.lower()
            if key not in seen:
                seen.add(key)
                unique.append(t)
        return unique

    def run_genre_copy(self) -> None:
        genre_url = self.entry_copy_genre_url.get().strip()
        dest_str = self.entry_copy_dest.get().strip()
        src_str = self.entry_copy_src.get().strip()

        if not genre_url:
            self.log("❌ [Genre Copy] Vui lòng nhập URL thể loại.")
            return
        if not dest_str:
            self.log("❌ [Genre Copy] Vui lòng chọn thư mục đích.")
            return

        try:
            start_page = int(self.copy_page_start.get())
            end_page = int(self.copy_page_end.get())
            if start_page < 1 or end_page < start_page:
                raise ValueError
        except ValueError:
            self.log("❌ [Genre Copy] Page range không hợp lệ.")
            return

        dest_dir = Path(dest_str)
        src_dir = Path(src_str) if src_str else Path(self.entry_path.get().strip())

        if not src_dir.exists():
            self.log(f"❌ [Genre Copy] Thư mục nguồn không tồn tại: {src_dir}")
            return

        dest_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"📂 Nguồn  : {src_dir}")
        self.log(f"📂 Đích   : {dest_dir}")

        self.log(f"🔍 Bắt đầu quét thể loại (trang {start_page}–{end_page})...")
        
        try:
            titles = self._scrape_story_titles_from_genre(genre_url, start_page, end_page)
        finally:
            self._restart_driver()

        if not titles:
            self.log("⚠️ [Genre Copy] Không tìm thấy tên truyện nào trong thể loại này.")
            return

        self.log(f"✅ Quét xong: {len(titles)} tên truyện duy nhất.")

        self.log("📦 Đang xây dựng index EPUB từ thư mục nguồn...")
        epub_index: Dict[str, Path] = {}
        for epub_file in src_dir.rglob("*.epub"):
            try:
                epub_file.relative_to(dest_dir)
                continue
            except ValueError:
                pass
            normalized_stem = self._normalize_for_match(epub_file.stem)
            epub_index[normalized_stem] = epub_file

        self.log(f"📊 Index: {len(epub_index)} file EPUB.")
        if not epub_index:
            self.log("⚠️ Không tìm thấy file EPUB nào trong thư mục nguồn.")
            return

        copied = 0
        skipped_exists = 0
        not_found = 0

        for idx, title in enumerate(titles, 1):
            if not self.is_running:
                break

            self._set_progress(idx / len(titles))
            norm_title = self._normalize_for_match(title)

            matched_path: Optional[Path] = best_title_match(norm_title, epub_index)

            if matched_path is None:
                self.log(f"[{idx}/{len(titles)}] 🔎 Không tìm thấy: {title}")
                not_found += 1
                continue

            target = dest_dir / matched_path.name
            if target.exists() and not self.overwrite_var.get():
                self.log(f"[{idx}/{len(titles)}] ⏭️ Đã có sẵn: {matched_path.name}")
                skipped_exists += 1
                continue

            try:
                use_copy = self.copy_mode_var.get()
                if use_copy:
                    shutil.copy2(str(matched_path), target)
                    self.log(f"[{idx}/{len(titles)}] ✅ Đã copy: {matched_path.name}")
                else:
                    shutil.move(str(matched_path), target)
                    self.log(f"[{idx}/{len(titles)}] ✅ Đã move: {matched_path.name}")
                copied += 1
            except OSError as exc:
                op = "copy" if self.copy_mode_var.get() else "move"
                self.log(f"[{idx}/{len(titles)}] ❌ Lỗi {op} {matched_path.name}: {exc}")

        op_label = "copy" if self.copy_mode_var.get() else "move"
        self.log("─" * 50)
        self.log(f"🏁 Hoàn tất Genre {op_label.title()}!")
        self.log(f"   ✅ Đã {op_label}    : {copied} file")
        self.log(f"   ⏭️ Đã có sẵn : {skipped_exists} file")
        self.log(f"   🔎 Không thấy : {not_found} truyện")

    def _setup_logs_tab(self) -> None:
        tab = self.tab_logs
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))

        ctk.CTkButton(
            toolbar, text="🗑 Clear", width=90, height=28,
            fg_color=self.BG_INPUT, hover_color=self.BORDER_COLOR,
            font=("Inter", 10, "bold"),
            command=self._clear_logs,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            toolbar, text="📋 Copy All", width=100, height=28,
            fg_color=self.BG_INPUT, hover_color=self.BORDER_COLOR,
            font=("Inter", 10, "bold"),
            command=self._copy_logs,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            toolbar, text="🩺 Kiểm tra selector", width=150, height=28,
            fg_color=self.BG_INPUT, hover_color=self.BORDER_COLOR,
            font=("Inter", 10, "bold"),
            command=self._check_selectors_action,
        ).pack(side="left")

        self.log_box = ctk.CTkTextbox(tab, font=("Consolas", 10), fg_color=self.BG_INPUT, border_width=1, border_color=self.BORDER_COLOR)
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 10))

    def _clear_logs(self) -> None:
        self.log_box.delete("1.0", "end")

    def _copy_logs(self) -> None:
        content = self.log_box.get("1.0", "end").strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            self.log("📋 Đã copy log ra clipboard.")

    def _check_selectors_action(self) -> None:
        """Nút 'Kiểm tra selector': dùng URL ở ô URL tab Tải Truyện, tải HTML bằng requests rồi báo cáo.

        Chỉ dùng requests (không đụng trình duyệt Selenium) nên chạy song song với tác vụ tải được.
        Giá trị UI được đọc ở luồng chính rồi mới giao cho luồng nền.
        """
        url = self.entry_combined_url.get().strip()
        if not url:
            self.log("❌ Hãy dán URL trang thể loại hoặc trang truyện vào ô URL (tab Tải Truyện) rồi bấm lại.")
            return
        site = detect_site(url)
        if not site:
            self.log("⚠️ Chưa hỗ trợ kiểm tra selector cho site này (hỗ trợ: dtv, monkeydd, trichtinhlau, "
                     "truyenfull, docln/hako, khosach.mnd, metruyenchu, tangthuvien).")
            return
        selectors = dict(self._selectors)
        proxies = requests_proxies(url, self._site_proxy())
        self.tabview.set("📋 Activity Logs")
        self.log(f"🩺 Đang tải trang để kiểm tra selector ({site})...")
        threading.Thread(
            target=self._check_selectors_worker, args=(url, site, selectors, proxies), daemon=True
        ).start()

    def _check_selectors_worker(self, url: str, site: str, selectors: Dict[str, Any], proxies) -> None:
        try:
            resp = self.http_session.get(url, timeout=(5, 15), proxies=proxies)
            lines = build_report(url, site, resp.text, resp.status_code, selectors)
        except Exception as exc:
            self.log(f"❌ Không tải được trang để kiểm tra: {type(exc).__name__}: {str(exc)[:100]}")
            return
        for line in lines:
            self.log(line)

    def log(self, message: str) -> None:
        self.after(0, self._log_safe, message)

    def _log_safe(self, message: str) -> None:
        try:
            self.log_box.insert("end", f"{time.strftime('%H:%M:%S')} - {message}\n")
            self.log_box.see("end")
        except Exception:
            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

    def browse_path(self):
        path = filedialog.askdirectory()
        if path:
            self.entry_path.delete(0, "end")
            self.entry_path.insert(0, path)
