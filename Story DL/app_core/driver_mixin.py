"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import logging

import undetected_chromedriver as uc

import os
import re
import socket
import subprocess
import sys
import time
import shutil
from pathlib import Path
from typing import Optional

from selenium import webdriver as selenium_webdriver

from app_core.constants import BASE_PATH
from app_core.net_utils import chrome_proxy_arg

from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException



_dbg = logging.getLogger(__name__)


class DriverMixin:
    _cf_visible: bool = False          # Cloudflare buộc phải có cửa sổ để người dùng xác minh
    _real_chrome: bool = False         # dùng Chrome thật (do người dùng xác minh tay) thay vì uc
    _real_chrome_failed: bool = False  # đã thử Chrome thật nhưng không được -> quay lại uc
    _chrome_proc: Optional[subprocess.Popen] = None

    def _site_proxy(self) -> str:
        """Proxy (vd. byedpi) người dùng nhập ở ô 'Proxy trichtinhlau'; '' nếu để trống."""
        w = getattr(self, "entry_trichtinhlau_proxy", None)
        try:
            return w.get().strip() if w is not None else ""
        except Exception:
            return ""

    def _is_headless(self) -> bool:
        """Headless theo UI, trừ khi đã bị buộc hiện cửa sổ vì Cloudflare."""
        return bool(self.headless_var.get()) and not (self._cf_visible or self._real_chrome)

    def _restart_driver(self) -> None:
        """Đóng driver và (nếu có) tiến trình Chrome thật do app mở."""
        d, self.driver = self.driver, None
        if d:
            try:
                d.quit()
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
        proc, self._chrome_proc = self._chrome_proc, None
        if proc and proc.poll() is None:
            try:
                if sys.platform.startswith("win"):
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   capture_output=True, timeout=10)
                else:
                    proc.terminate()
                    proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

    @staticmethod
    def _find_chrome() -> Optional[str]:
        """Tìm chrome đã cài (registry/Program Files trên Windows, PATH trên Linux/macOS)."""
        candidates = []
        if sys.platform.startswith("win"):
            try:
                import winreg
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as k:
                            candidates.append(winreg.QueryValue(k, None))
                    except OSError:
                        pass
            except ImportError:
                pass
            for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                base = os.environ.get(env)
                if base:
                    candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
        elif sys.platform == "darwin":
            candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        else:
            for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
                found = shutil.which(name)
                if found:
                    candidates.append(found)
        return next((c for c in candidates if c and os.path.isfile(c)), None)

    def _init_real_chrome(self):
        """Mở Chrome thật như người dùng bình thường (không cờ automation) rồi attach qua debugger port.

        Người dùng tự xác minh Cloudflare trên cửa sổ này; profile riêng được giữ lại nên
        cookie cf_clearance còn hiệu lực cho các lần sau.
        """
        chrome = self._find_chrome()
        if not chrome:
            raise RuntimeError("Không tìm thấy Google Chrome trên máy.")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        profile = BASE_PATH / "chrome_profile_real"
        profile.mkdir(parents=True, exist_ok=True)
        self._chrome_proc = subprocess.Popen(
            [chrome, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
             "--no-first-run", "--no-default-browser-check", "--lang=vi-VN",
             *([chrome_proxy_arg(self._site_proxy())] if self._site_proxy() else []), "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Chrome không mở cổng điều khiển trong 20s.")
                    time.sleep(0.3)
            opts = selenium_webdriver.ChromeOptions()
            opts.debugger_address = f"127.0.0.1:{port}"
            driver = selenium_webdriver.Chrome(options=opts)
            driver.set_page_load_timeout(30)
            return driver
        except Exception:
            self._restart_driver()
            raise

    def get_valid_driver(self):
        if self.driver:
            try:
                _ = self.driver.title
                return self.driver
            except Exception:
                self.log("⚠️ Trình duyệt gặp sự cố, đang khởi tạo lại Driver mới...")
                self._restart_driver()

        self.driver = self.init_driver()
        return self.driver

    def _nav(self, url: str):
        """``driver.get`` chịu lỗi, trả về driver đang dùng.

        - Hết thời gian tải trang (page_load_timeout 30s): dừng tải rồi dùng tiếp DOM đã có,
          thay vì ném TimeoutException làm mất cả truyện đang cào.
        - Driver/Chrome đã chết: khởi động lại và thử lại đúng 1 lần.
        """
        for attempt in range(2):
            driver = self.get_valid_driver()
            try:
                driver.get(url)
                return driver
            except TimeoutException:
                try:
                    driver.execute_script("window.stop();")
                except Exception:
                    _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
                return driver
            except Exception:
                if attempt == 1:
                    raise
                self.log("⚠️ Trình duyệt lỗi khi mở trang, khởi tạo lại rồi thử lại...")
                self._restart_driver()
        return self.get_valid_driver()

    def init_driver(self):
        if self._real_chrome:
            try:
                self.log("🌐 Mở Chrome thật — hãy tự xác minh Cloudflare trên cửa sổ này nếu được yêu cầu...")
                return self._init_real_chrome()
            except Exception as exc:
                self.log(f"⚠️ Không dùng được Chrome thật ({str(exc)[:80]}), quay lại chế độ tự động.")
                self._real_chrome, self._real_chrome_failed, self._cf_visible = False, True, True
        headless = self._is_headless()  # đọc 1 lần
        # Profile riêng, lưu lâu dài: cookie cf_clearance sau khi bạn xác minh tay
        # được giữ lại nên các lần chạy sau thường không phải xác minh lại.
        profile_dir = BASE_PATH / "chrome_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)

        def create_options():
            opt = uc.ChromeOptions()
            if headless:
                opt.add_argument('--headless=new')
            opt.add_argument('--no-sandbox')
            opt.add_argument('--disable-dev-shm-usage')
            opt.add_argument('--disable-notifications')
            opt.add_argument('--lang=vi-VN,vi;q=0.9')
            opt.add_argument('--disable-popup-blocking')
            opt.add_argument('--disable-extensions')
            opt.add_argument('--disable-plugins')
            opt.add_argument('--dns-prefetch-disable')
            opt.add_argument('--disable-background-networking')
            opt.add_argument('--disable-sync')
            proxy_arg = chrome_proxy_arg(self._site_proxy())
            if proxy_arg:
                opt.add_argument(proxy_arg)

            opt.page_load_strategy = 'eager'
            opt.add_experimental_option(
                "prefs", {"profile.managed_default_content_settings.images": 2}
            )
            return opt

        def clear_uc_cache():
            import tempfile
            try:
                uc_path = Path(tempfile.gettempdir()) / "undetected_chromedriver"
                if uc_path.exists():
                    shutil.rmtree(uc_path, ignore_errors=True)
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)


        def finalize(driver):
            driver.set_page_load_timeout(30)
            if not headless:
                try: driver.set_window_position(3000, 3000)
                except Exception:
                    _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
            return driver

        try:
            self.log(f"⚙️ Khởi tạo trình duyệt (Ẩn: {'Bật' if headless else 'Tắt'})...")
            return finalize(uc.Chrome(options=create_options(), user_data_dir=str(profile_dir), use_subprocess=True))
        except Exception as e:
            error_msg = str(e)
            if "session not created" in error_msg.lower():
                self.log("⚠️ Lỗi phiên bản Driver. Đang tự sửa...")
                clear_uc_cache()
                match = re.search(r"browser version is ([\d.]+)", error_msg)
                v_main = int(match.group(1).split('.')[0]) if match else None
                try:
                    return finalize(uc.Chrome(options=create_options(), user_data_dir=str(profile_dir), version_main=v_main, use_subprocess=True))
                except Exception as e2:
                    self.log(f"❌ THẤT BẠI: {str(e2)[:100]}")
            raise e

    def wait_for_cloudflare(self):
        try:
            check_interval = 2.0
            max_wait = 180  # đủ thời gian để người dùng tự bấm xác minh trên cửa sổ trình duyệt
            wait_time = 0.0
            last_log = -999.0

            while self.is_running and wait_time < max_wait:
                try:
                    driver = self.get_valid_driver()
                    page_title = driver.title.lower()
                    is_cf_page = False
                    cf_ids = ["challenge-running", "challenge-stage", "challenge-form", "cf-wrapper"]
                    for cid in cf_ids:
                        if driver.find_elements(By.ID, cid):
                            is_cf_page = True
                            break

                    if not is_cf_page:
                        if any(x in page_title for x in ["just a moment", "cloudflare", "checking your browser", "xác minh bảo mật", "xác minh bạn là con người"]):
                            is_cf_page = True

                    if is_cf_page and not self._real_chrome and not self._real_chrome_failed:
                        # Chrome do tool điều khiển bị Turnstile từ chối -> mở Chrome thật để người dùng xác minh
                        url = driver.current_url
                        self.log("🛑 Cloudflare yêu cầu xác minh — chuyển sang Chrome thật, hãy tự xác minh (bấm ô kiểm nếu có)...")
                        self._cf_visible = self._real_chrome = True
                        self._restart_driver()
                        self.get_valid_driver().get(url)
                        continue

                    if is_cf_page:
                        if not self._is_headless():
                            try:
                                driver.set_window_position(100, 100)
                                driver.maximize_window()
                            except Exception:
                                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

                        if wait_time - last_log >= 10:
                            last_log = wait_time
                            self.log("🛑 PHÁT HIỆN CLOUDFLARE! Đang đưa trình duyệt lên để bạn xác minh...")

                        self._sleep(check_interval)
                        wait_time += check_interval
                    else:
                        if not self._is_headless() and not self._real_chrome:
                            try:
                                driver.set_window_position(3000, 3000)
                            except Exception:
                                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
                        if wait_time > 0:  # vừa qua xác minh -> dùng chung cookie/UA cho requests
                            self._sync_driver_cookies_to_session()
                        return len(driver.page_source) > 800 and "cloudflare" not in driver.title.lower()
                except Exception as exc:
                    _dbg.debug("Lỗi khi chờ Cloudflare", exc_info=True)
                    self.log(f"   ⚠️ Trình duyệt lỗi khi chờ trang tải: {type(exc).__name__}: {str(exc)[:80]}")
                    return False
            return False
        except Exception:
            _dbg.debug("Lỗi ngoài vòng chờ Cloudflare (coi như đã qua)", exc_info=True)
            return True

    def _sync_driver_cookies_to_session(self, domain_hint: str = "") -> None:
        if not self.driver:
            return
        try:
            for c in self.driver.get_cookies():
                if domain_hint and domain_hint not in c.get("domain", ""):
                    continue
                self.http_session.cookies.set(
                    c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/")
                )
            try:
                ua = self.driver.execute_script("return navigator.userAgent;")
                if ua:
                    self.http_session.headers["User-Agent"] = ua
            except Exception:
                _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
        except Exception:
            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
