"""Khởi tạo một lần khi chạy app (gọi từ main.py trước khi tạo cửa sổ).

Tách khỏi ``constants.py`` để import hằng số/hàm thuần (vd. trong test) không phải
kéo theo undetected_chromedriver và không tự đổi cấu hình logging của chương trình khác.

Bật log chi tiết (ghi cả lỗi bị nuốt) bằng biến môi trường ``STORYLOADER_DEBUG=1`` hoặc tham số
``--debug``: log được ghi thêm vào ``debug.log`` cạnh app.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from app_core.constants import BASE_PATH

DEBUG_LOG_FILE = BASE_PATH / "debug.log"


def patch_undetected_chromedriver() -> None:
    """``uc.Chrome.__del__`` hay ném OSError/AttributeError khi thoát -> nuốt riêng 2 lỗi đó."""
    import undetected_chromedriver as uc

    if getattr(uc.Chrome, "_story_loader_patched", False):
        return
    original_del = uc.Chrome.__del__

    def safe_del(self):
        try:
            original_del(self)
        except (OSError, AttributeError):
            pass

    uc.Chrome.__del__ = safe_del
    uc.Chrome._story_loader_patched = True


def setup_logging(debug: bool | None = None) -> None:
    if debug is None:
        debug = os.environ.get("STORYLOADER_DEBUG", "") not in ("", "0") or "--debug" in sys.argv
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    if debug:
        root.setLevel(logging.DEBUG)
        for noisy in ("urllib3", "selenium", "undetected_chromedriver", "PIL", "asyncio", "charset_normalizer"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        try:
            fh = RotatingFileHandler(DEBUG_LOG_FILE, maxBytes=2_000_000, backupCount=1, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s:%(lineno)d - %(message)s"))
            root.addHandler(fh)
            logging.getLogger(__name__).info("Debug bật — ghi chi tiết vào %s", DEBUG_LOG_FILE)
        except OSError as exc:
            logging.getLogger(__name__).warning("Không tạo được debug.log: %s", exc)


def setup() -> None:
    setup_logging()
    patch_undetected_chromedriver()
