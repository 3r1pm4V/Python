"""Test EpubBuilderMixin (cần ebooklib; tự bỏ qua nếu chưa cài)."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("ebooklib")

from bs4 import BeautifulSoup  # noqa: E402

from app_core.epub_builder_mixin import EpubBuilderMixin  # noqa: E402
from app_core.net_utils import is_valid_epub  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class Builder(EpubBuilderMixin):
    def __init__(self) -> None:
        self.msgs = []

    def log(self, message: str) -> None:
        self.msgs.append(message)


def _names(path: Path):
    with zipfile.ZipFile(path) as z:
        return z.namelist()


def test_create_epub_writes_valid_file_with_all_chapters(tmp_path: Path) -> None:
    chapters = [("Chương 1", "Dòng một\nDòng hai"), ("Chương 2", "<p>Đã là HTML</p>"), ("", "Không có tiêu đề")]
    b = Builder()
    assert b.create_epub("Truyện Thử", chapters, tmp_path, author="Tác Giả")

    out = tmp_path / "Truyện Thử.epub"
    assert out.exists() and is_valid_epub(out)
    chap_files = [n for n in _names(out) if re.search(r"chap_\d+\.xhtml$", n)]
    assert len(chap_files) == 3
    assert not list(tmp_path.glob("*.part"))                  # không để lại file dở dang


def test_create_epub_sanitizes_forbidden_filename_chars(tmp_path: Path) -> None:
    assert Builder().create_epub('Tên: "lạ"?', [("c", "x")], tmp_path)
    files = [p.name for p in tmp_path.glob("*.epub")]
    assert len(files) == 1
    assert not set(files[0]) & set('<>:"/\\|?*')


def test_create_epub_includes_cover_with_real_extension(tmp_path: Path) -> None:
    assert Builder().create_epub("Có Bìa", [("c", "x")], tmp_path, cover_image_data=PNG)
    assert any(n.endswith("cover.png") for n in _names(tmp_path / "Có Bìa.epub"))


def test_create_epub_failure_returns_false_and_logs(tmp_path: Path) -> None:
    b = Builder()
    assert b.create_epub("Hỏng", [("c", "x")], tmp_path / "thư-mục-không-tồn-tại") is False
    assert any("Lỗi tạo EPUB" in m for m in b.msgs)


@pytest.mark.parametrize("data,expected", [
    (PNG, "cover.png"),
    (b"GIF89a....", "cover.gif"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "cover.webp"),
    (b"\xff\xd8\xff\xe0JFIF", "cover.jpg"),
    (b"khong ro", "cover.jpg"),
])
def test_cover_filename_follows_content(data: bytes, expected: str) -> None:
    assert EpubBuilderMixin._cover_filename(data) == expected


def test_extract_visible_paragraphs_skips_hidden() -> None:
    html = (
        '<div><p>Hiện</p><p style="display: none">Ẩn 1</p><p style="visibility:hidden">Ẩn 2</p>'
        '<p style="height:0">Ẩn 3</p><p>  </p><p>Hiện nữa</p></div>'
    )
    container = BeautifulSoup(html, "html.parser").div
    assert EpubBuilderMixin._extract_visible_paragraphs(container) == ["Hiện", "Hiện nữa"]
