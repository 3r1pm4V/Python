"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import customtkinter as ctk

import json
import logging
from typing import Dict, Any


from app_core.constants import (
    BASE_PATH, CONFIG_FILE, SELECTORS_FILE, DEFAULT_SELECTORS,
)


_dbg = logging.getLogger(__name__)


class ConfigMixin:
    _KEYRING_SERVICE: str = "StoryLoader"
    _KEYRING_USER: str = "wattpad_cookie"
    _COOKIE_FALLBACK_NAME: str = ".wattpad_cookie.b64"

    def _load_config(self) -> Dict[str, Any]:
        if not CONFIG_FILE.exists():
            return {}
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logging.warning(f"Không đọc được config: {exc}")
            return {}

    def _save_config(self) -> None:
        cfg: Dict[str, Any] = {}

        def _get(widget_name: str, default: Any = "") -> Any:
            w = getattr(self, widget_name, None)
            if w is None:
                return default
            try:
                if isinstance(w, ctk.CTkEntry):
                    return w.get()
                if isinstance(w, ctk.BooleanVar):
                    return w.get()
                if isinstance(w, ctk.StringVar):
                    return w.get()
            except Exception:
                # Widget đã bị destroy (ví dụ tab được rebuild khi đổi
                # source/mode) nhưng attribute Python vẫn còn tham chiếu tới
                # nó -> Tcl báo "invalid command name". Coi như không có giá
                # trị và dùng default thay vì làm sập app lúc đóng cửa sổ.
                return default
            return default

        cfg["output_path"]            = _get("entry_path")
        cfg["headless"]               = _get("headless_var", True)
        cfg["trichtinhlau_proxy"]     = _get("entry_trichtinhlau_proxy")
        cfg["overwrite"]              = _get("overwrite_var", False)
        cfg["completed_only"]         = _get("completed_only_var", False)

        cfg["combined_url"]           = _get("entry_combined_url")
        cfg["source_option"]          = _get("source_option_var")
        cfg["download_mode"]          = _get("download_mode_var")
        cfg["genre_page_start"]       = _get("page_start", "1")
        cfg["genre_page_end"]         = _get("page_end", "1")

        cfg["wattpad_url"]            = _get("entry_wattpad_url")
        cfg["wattpad_chap_start"]     = _get("wattpad_chap_start", "1")
        cfg["wattpad_chap_end"]       = _get("wattpad_chap_end", "0")
        cfg["wattpad_proxy"]          = _get("entry_wattpad_proxy")
        cfg["wattpad_tag_limit"]      = _get("wattpad_tag_limit", "50")
        cfg["wattpad_required_tags"]  = _get("entry_wattpad_required_tags")

        raw_cookie = _get("entry_wattpad_cookie", "")
        if raw_cookie:
            self._keyring_set_cookie(raw_cookie)
        elif (getattr(self, "entry_wattpad_cookie", None) is not None
              and not getattr(self, "_cookie_restore_failed", False)):
            # Người dùng đã xoá ô cookie -> xoá luôn bản đã lưu. KHÔNG xoá nếu lúc khởi động đọc
            # cookie đã lưu thất bại (keyring lỗi tạm thời): ô rỗng lúc đó không phải ý người dùng.
            self._keyring_clear_cookie()
        cfg["wattpad_cookie_saved"] = bool(raw_cookie)

        cfg["copy_genre_url"]         = _get("entry_copy_genre_url")
        cfg["copy_page_start"]        = _get("copy_page_start", "1")
        cfg["copy_page_end"]          = _get("copy_page_end", "1")
        cfg["copy_dest"]              = _get("entry_copy_dest")
        cfg["copy_src"]               = _get("entry_copy_src")
        cfg["copy_mode_copy"]         = _get("copy_mode_var", True)

        try:
            CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logging.warning(f"Không ghi được config: {exc}")

    def _restore_config(self) -> None:
        cfg = self._config
        if not cfg:
            return

        def _set_entry(widget_name: str, key: str) -> None:
            w = getattr(self, widget_name, None)
            if w is None or key not in cfg:
                return
            val = cfg[key]
            if isinstance(w, ctk.CTkEntry):
                w.delete(0, "end")
                w.insert(0, str(val))
            elif isinstance(w, ctk.BooleanVar):
                w.set(bool(val))
            elif isinstance(w, ctk.StringVar):
                w.set(str(val))

        _set_entry("entry_path",             "output_path")
        _set_entry("headless_var",           "headless")
        _set_entry("entry_trichtinhlau_proxy", "trichtinhlau_proxy")
        _set_entry("overwrite_var",          "overwrite")
        _set_entry("completed_only_var",     "completed_only")

        _set_entry("entry_combined_url",     "combined_url")
        _set_entry("source_option_var",      "source_option")
        _set_entry("download_mode_var",      "download_mode")
        _set_entry("page_start",             "genre_page_start")
        _set_entry("page_end",               "genre_page_end")

        _set_entry("entry_wattpad_url",      "wattpad_url")
        _set_entry("wattpad_chap_start",     "wattpad_chap_start")
        _set_entry("wattpad_chap_end",       "wattpad_chap_end")
        _set_entry("entry_wattpad_proxy",    "wattpad_proxy")
        _set_entry("wattpad_tag_limit",      "wattpad_tag_limit")
        _set_entry("entry_wattpad_required_tags", "wattpad_required_tags")

        if cfg.get("wattpad_cookie_saved"):
            stored = self._keyring_get_cookie()
            if stored:
                w = getattr(self, "entry_wattpad_cookie", None)
                if w:
                    w.delete(0, "end")
                    w.insert(0, stored)
            else:
                self._cookie_restore_failed = True

        _set_entry("entry_copy_genre_url",   "copy_genre_url")
        _set_entry("copy_page_start",        "copy_page_start")
        _set_entry("copy_page_end",          "copy_page_end")
        _set_entry("copy_dest",              "copy_dest")
        _set_entry("copy_src",               "copy_src")
        _set_entry("copy_mode_var",          "copy_mode_copy")

    def _ensure_selectors_file(self) -> None:
        if not SELECTORS_FILE.exists():
            try:
                SELECTORS_FILE.write_text(
                    json.dumps(DEFAULT_SELECTORS, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self.log(f"📝 Đã tạo file selector: {SELECTORS_FILE.name}")
            except Exception as exc:
                logging.warning(f"Không tạo được selector file: {exc}")

    def _load_selectors(self) -> Dict[str, Any]:
        if not SELECTORS_FILE.exists():
            return DEFAULT_SELECTORS
        try:
            loaded = json.loads(SELECTORS_FILE.read_text(encoding="utf-8"))
            merged: Dict[str, Any] = {}
            for site, defaults in DEFAULT_SELECTORS.items():
                if isinstance(defaults, dict):
                    merged[site] = {**defaults, **(loaded.get(site) or {})}
                else:
                    merged[site] = loaded.get(site, defaults)
            return merged
        except Exception as exc:
            logging.warning(f"Không đọc được selector file ({exc}), dùng default.")
            return DEFAULT_SELECTORS

    def _sel(self, site: str, key: str) -> Any:
        return (self._selectors.get(site) or {}).get(key, "")

    def _check_keyring(self) -> bool:
        try:
            import keyring  # noqa: F401
            keyring.set_password(self._KEYRING_SERVICE, "__test__", "ok")
            val = keyring.get_password(self._KEYRING_SERVICE, "__test__")
            keyring.delete_password(self._KEYRING_SERVICE, "__test__")
            return val == "ok"
        except Exception:
            return False

    def _keyring_set_cookie(self, cookie: str) -> None:
        try:
            import keyring
            keyring.set_password(self._KEYRING_SERVICE, self._KEYRING_USER, cookie)
            (BASE_PATH / self._COOKIE_FALLBACK_NAME).unlink(missing_ok=True)  # xoá bản base64 cũ
        except Exception:
            import base64
            obfuscated = base64.b64encode(cookie.encode()).decode()
            fallback_file = BASE_PATH / self._COOKIE_FALLBACK_NAME
            try:
                fallback_file.write_text(obfuscated, encoding="utf-8")
            except Exception as exc:
                logging.warning(f"Không lưu được cookie: {exc}")

    def _keyring_clear_cookie(self) -> None:
        try:
            import keyring
            keyring.delete_password(self._KEYRING_SERVICE, self._KEYRING_USER)
        except Exception:
            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)  # chưa lưu / keyring không khả dụng
        try:
            (BASE_PATH / self._COOKIE_FALLBACK_NAME).unlink(missing_ok=True)
        except Exception:
            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)

    def _keyring_get_cookie(self) -> str:
        try:
            import keyring
            val = keyring.get_password(self._KEYRING_SERVICE, self._KEYRING_USER)
            if val:
                return val
        except Exception:
            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
        import base64
        fallback_file = BASE_PATH / self._COOKIE_FALLBACK_NAME
        try:
            if fallback_file.exists():
                return base64.b64decode(fallback_file.read_text(encoding="utf-8").strip()).decode()
        except Exception:
            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
        return ""
