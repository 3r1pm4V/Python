"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Tuple, Optional, Dict
from urllib.parse import urlparse, unquote

import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except ImportError:
    from requests.packages.urllib3.util.retry import Retry

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app_core.constants import (
    INVALID_FS_CHARS_RE, GDRIVE_HEADERS,
)


from app_core.net_utils import get_with_retry, is_valid_epub


class HttpMixin:
    @staticmethod
    def _build_pooled_session() -> requests.Session:
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'})
        retry = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
            raise_on_status=False,  # hết lượt retry thì trả response (get_with_retry/caller tự xét), không ném RetryError
        )
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _net_get_with_retry(
        self,
        session,
        url: str,
        *,
        retries: int = 2,
        backoff: float = 1.0,
        stream: bool = False,
        timeout: Tuple[int, int] = (5, 15),
        label: str = "",
        headers: Optional[Dict[str, str]] = None,
    ):
        return get_with_retry(
            session, url, attempts=max(1, retries), backoff=backoff, stream=stream,
            timeout=timeout, headers=headers, label=label, log=self.log,
            sleep=self._sleep,  # backoff ngắt được khi bấm STOP
        )

    @staticmethod
    def _ensure_curl_cffi():
        try:
            import curl_cffi  # noqa: F401
        except ImportError:
            raise ImportError(
                "Thiếu thư viện curl_cffi.\n"
                "Cài đặt bằng lệnh:  pip install curl_cffi\n"
                "Hoặc nếu dùng venv:  pip install curl_cffi --upgrade"
            )

    @staticmethod
    def _save_stream_as_epub(resp, save_path: Path) -> bool:
        """Ghi stream vào ``<save_path>.part``, kiểm tra là EPUB (ZIP) rồi mới đổi tên.

        Tránh để file dở dang/HTML lỗi nằm ở đường dẫn cuối (sẽ bị coi là "đã tải").
        Bộ nhớ O(1): ghi theo chunk 64 KB.
        """
        part = save_path.with_name(save_path.name + ".part")
        try:
            with open(part, "wb") as f:
                for chunk in resp.iter_content(65536):
                    if chunk:
                        f.write(chunk)
            if not is_valid_epub(part):
                return False
            os.replace(part, save_path)
            return True
        finally:
            part.unlink(missing_ok=True)

    def extract_google_drive_id(self, url: str) -> Optional[str]:
        patterns = [r'id=([a-zA-Z0-9_-]+)', r'/d/([a-zA-Z0-9_-]+)', r'/file/d/([a-zA-Z0-9_-]+)']
        for p in patterns:
            m = re.search(p, url)
            if m: return m.group(1)
        return None

    def download_from_gdrive(self, url: str, folder_path: Path, book_name: str) -> Optional[str]:
        file_id = self.extract_google_drive_id(url)
        if not file_id: return None

        download_url = f"https://docs.google.com/uc?export=download&id={file_id}"
        session = self.http_session

        try:
            resp = self._net_get_with_retry(
                session, download_url, stream=True, timeout=(5, 30), label="GDrive", headers=GDRIVE_HEADERS
            )
            content_type = resp.headers.get('Content-Type', '').lower()

            if 'text/html' in content_type:
                body = resp.text or ""  # trang HTML nhỏ; KHÔNG đọc .text với file nhị phân
                confirm_token = None
                
                for key, value in session.cookies.items():
                    if key.startswith('download_warning'):
                        confirm_token = value
                        break
                
                if not confirm_token and body:
                    m = re.search(r'confirm=([^&"\']+)', body)
                    if m:
                        confirm_token = m.group(1)

                if not confirm_token:
                    confirm_token = "t"

                confirm_url = f"{download_url}&confirm={confirm_token}"
                resp = self._net_get_with_retry(
                    session, confirm_url, stream=True, timeout=(5, 60), label="GDrive-confirm", headers=GDRIVE_HEADERS
                )

            final_filename = book_name
            content_disposition = resp.headers.get("Content-Disposition", "")
            
            if content_disposition:
                fname_match = re.search(r"filename\*=UTF-8''([^;\n]+)", content_disposition, re.IGNORECASE)
                if fname_match:
                    final_filename = unquote(fname_match.group(1)).strip()
                else:
                    fname_match = re.search(r'filename="?([^";\n]+)"?', content_disposition, re.IGNORECASE)
                    if fname_match:
                        raw_fname = fname_match.group(1).strip()
                        try:
                            final_filename = raw_fname.encode('latin-1').decode('utf-8')
                        except (UnicodeEncodeError, UnicodeDecodeError):
                            final_filename = unquote(raw_fname)

            if final_filename.lower().endswith(".epub"):
                final_filename = final_filename[:-5]

            safe_filename = (
                INVALID_FS_CHARS_RE.sub('_', final_filename).strip()
                or INVALID_FS_CHARS_RE.sub('_', book_name).strip()
                or "download"
            )
            save_path = folder_path / f"{safe_filename}.epub"

            if not self._save_stream_as_epub(resp, save_path):
                self.log(f"   ❌ File tải về không phải EPUB hợp lệ (link hết hạn/hết quota/cần quyền), đã huỷ: {safe_filename}.epub")
                return None

            self.log(f"   ✅ Đã tải thành công từ Google Drive: {safe_filename}.epub")
            return safe_filename
        except OSError as e:
            self.log(f"   ❌ Lỗi ghi file khi tải từ Google Drive cho {book_name}: {e}")
            return None
        except Exception as e:
            self.log(f"   ❌ Tải thất bại từ Google Drive cho {book_name}: {e}")
            return None

    def download_general(self, url: str, folder_path: Path, book_name: str) -> Optional[str]:
        if not url: return None

        if any(x in url.lower() for x in ["google.com", "drive.google.com", "docs.google.com"]):
            return self.download_from_gdrive(url, folder_path, book_name)

        safe_book_name = INVALID_FS_CHARS_RE.sub('_', book_name).strip() or "download"
        try:
            save_path = folder_path / f"{safe_book_name}.epub"
            direct_url = url

            if "dtv-ebook.com.vn" in url.lower():
                self._sync_driver_cookies_to_session("dtv-ebook.com.vn")

            if "mediafire.com" in url:
                self.log("   - ☁️ Đang lấy link direct từ Mediafire...")
                driver = self.get_valid_driver()
                driver.get(url)
                dl_sel = self._sel("mediafire", "download_button") or "#downloadButton"
                try:
                    WebDriverWait(driver, self._wdwait()).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, dl_sel))
                    )
                    dl_btn = driver.find_element(By.CSS_SELECTOR, dl_sel)
                    direct_url = dl_btn.get_attribute("href") or url
                except Exception:
                    self.log("   ⚠️ Không tìm thấy nút download Mediafire, thử tải trực tiếp...")

            if direct_url:
                self.log(f"   - 📥 Đang tải từ: {urlparse(direct_url).netloc}...")
                resp = self._net_get_with_retry(
                    self.http_session, direct_url, stream=True, timeout=(5, 30), label=urlparse(direct_url).netloc
                )
                if resp.status_code == 200:
                    content_type = resp.headers.get('Content-Type', '').lower()
                    if 'text/html' in content_type:
                        self.log("   ❌ URL trả về trang web thay vì file. Link có thể hết hạn hoặc cần đăng nhập.")
                        return None
                    if not self._save_stream_as_epub(resp, save_path):
                        self.log("   ❌ File tải về không phải EPUB hợp lệ, đã huỷ.")
                        return None
                    self.log(f"   ✅ Tải thành công từ {urlparse(direct_url).netloc}!")
                    return safe_book_name
                self.log(f"   ❌ HTTP {resp.status_code} khi tải file.")
        except OSError as e:
            self.log(f"   ❌ Lỗi ghi file: {str(e)[:50]}")
        except Exception as e:
            self.log(f"   ❌ Lỗi tải file: {str(e)[:50]}")

        return None
