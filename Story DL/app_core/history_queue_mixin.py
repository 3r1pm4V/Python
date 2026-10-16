"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Set, Dict


from app_core.constants import (
    HISTORY_FILE, QUEUE_FILE, BLOCKED_FILE, INVALID_FS_CHARS_RE,
)


_dbg = logging.getLogger(__name__)


class HistoryQueueMixin:
    def normalize_url(self, url: str) -> str:
        if not url: return ""
        try:
            return url.split('?')[0].rstrip('/')
        except Exception:
            return url

    def load_history(self) -> Set[str]:
        self.downloaded_filenames: Dict[str, str] = {}
        if not HISTORY_FILE.exists():
            return set()
        try:
            content = HISTORY_FILE.read_text(encoding='utf-8')
        except Exception:
            return set()

        urls: Set[str] = set()
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            url_part, _, filename_part = line.partition("\t")
            normalized = self.normalize_url(url_part.strip())
            if not normalized:
                continue
            urls.add(normalized)
            filename_part = filename_part.strip()
            if filename_part:
                self.downloaded_filenames[normalized] = filename_part
        return urls

    def save_history(self, url: str, filename: Optional[str] = None) -> None:
        normalized = self.normalize_url(url)
        if not normalized:
            return
        with self._history_lock:
            if normalized not in self.downloaded_urls:
                try:
                    line = f"{normalized}\t{filename}" if filename else normalized
                    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                        f.write(f"{line}\n")
                    self.downloaded_urls.add(normalized)
                    if filename:
                        self.downloaded_filenames[normalized] = filename
                except Exception as exc:
                    logging.warning(f"Không ghi được history: {exc}")
            elif filename and normalized not in self.downloaded_filenames:
                self.downloaded_filenames[normalized] = filename

    def load_blocked(self) -> Set[str]:
        """Đọc blocked.txt (``url<TAB>lý do<TAB>tiêu đề`` mỗi dòng) -> tập URL đã chuẩn hoá."""
        if not BLOCKED_FILE.exists():
            return set()
        try:
            content = BLOCKED_FILE.read_text(encoding='utf-8')
        except Exception:
            return set()
        urls: Set[str] = set()
        for line in content.splitlines():
            url_part = line.split("\t", 1)[0].strip()
            normalized = self.normalize_url(url_part)
            if normalized:
                urls.add(normalized)
        return urls

    def save_blocked(self, url: str, reason: str = "", title: str = "") -> None:
        """Ghi nhớ truyện bị loại vĩnh viễn (BL) để các lần chạy sau không phải kiểm tra lại."""
        normalized = self.normalize_url(url)
        if not normalized:
            return
        with self._history_lock:
            if normalized in self.blocked_urls:
                return
            try:
                clean = lambda t: " ".join((t or "").split())  # không để TAB/xuống dòng phá định dạng file
                with open(BLOCKED_FILE, "a", encoding="utf-8") as f:
                    f.write(f"{normalized}\t{clean(reason)}\t{clean(title)}\n")
                self.blocked_urls.add(normalized)
            except Exception as exc:
                logging.warning(f"Không ghi được blocked: {exc}")

    def is_story_already_downloaded(
        self,
        url: str,
        dest_dir: Path,
        fallback_title: str,
        cache: Optional[Set[str]] = None,
    ) -> bool:
        normalized = self.normalize_url(url)
        if not normalized:
            return False

        if normalized in self.downloaded_urls:
            actual_filename = self.downloaded_filenames.get(normalized)
            story_name = actual_filename if actual_filename else fallback_title
            return self.check_epub_exists(dest_dir, story_name, cache=cache)

        if self.check_epub_exists(dest_dir, fallback_title, cache=cache):
            self.save_history(url, fallback_title)
            return True
        return False

    def queue_add(self, url: str) -> None:
        normalized = self.normalize_url(url)
        if not normalized:
            return
        with self._queue_lock:
            existing = self._queue_load_set()
            if normalized not in existing:
                try:
                    with open(QUEUE_FILE, "a", encoding="utf-8") as f:
                        f.write(f"{normalized}\n")
                except Exception as exc:
                    logging.warning(f"Không ghi được queue: {exc}")

    def queue_remove(self, url: str) -> None:
        normalized = self.normalize_url(url)
        if not normalized:
            return
        with self._queue_lock:
            lines = self._queue_load_raw()
            remaining = [ln for ln in lines if self.normalize_url(ln) != normalized]
            try:
                QUEUE_FILE.write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
            except Exception as exc:
                logging.warning(f"Không xóa được URL khỏi queue: {exc}")

    def _queue_load_raw(self) -> List[str]:
        if not QUEUE_FILE.exists():
            return []
        try:
            return [ln.strip() for ln in QUEUE_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except Exception:
            return []

    def _queue_load_set(self) -> Set[str]:
        return {self.normalize_url(ln) for ln in self._queue_load_raw()}

    @staticmethod
    def _name_matches(file_name: str, term: str, truncated: bool = False) -> bool:
        """Khớp khi tên file bắt đầu bằng ``term`` và kết thúc đúng ranh giới
        (hết tên, hoặc theo sau là ' - tác giả'). Tránh 'Đấu Phá' khớp 'Đấu Phá Thương Khung'."""
        if not file_name.startswith(term):
            return False
        if truncated:  # term đã bị cắt 50 ký tự -> chỉ so prefix
            return True
        rest = file_name[len(term):]
        return rest in ("", ".epub") or rest.startswith(" - ")

    def check_epub_exists(self, dest_dir: Path, story_name: str, cache: Optional[Set[str]] = None) -> bool:
        if not dest_dir.exists(): return False
        
        clean_name = INVALID_FS_CHARS_RE.sub('', story_name).strip().lower()
        underscore_name = INVALID_FS_CHARS_RE.sub('_', story_name).strip().lower()

        # File do app tạo dùng '_' thay ký tự cấm (create_epub) còn tên "sạch" bỏ hẳn ký tự đó:
        # khớp mờ phải thử CẢ HAI biến thể, nếu không file "tên_ x - tác giả.epub" bị tải lại.
        terms = []
        for nm in (clean_name, underscore_name):
            term = (nm[:50], len(nm) > 50)
            if len(term[0]) >= 5 and term not in terms:
                terms.append(term)

        if cache is not None:
            if f"{clean_name}.epub" in cache: return True
            if f"{underscore_name}.epub" in cache: return True
            return any(self._name_matches(f_name, t, tr) for t, tr in terms for f_name in cache)

        if (dest_dir / f"{clean_name}.epub").exists(): return True
        if (dest_dir / f"{underscore_name}.epub").exists(): return True

        if not terms:
            return False
        try:
            for f in dest_dir.rglob("*.epub"):
                f_name = f.name.lower()
                if any(self._name_matches(f_name, t, tr) for t, tr in terms): return True
        except Exception:
            _dbg.debug("Lỗi bị bỏ qua", exc_info=True)
        return False
