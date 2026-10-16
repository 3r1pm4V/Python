"""Chạy từ thư mục gốc: python -m pytest -q tests/test_title_filter.py"""
from __future__ import annotations

import pytest

from app_core.text_utils import find_blocked_title


@pytest.mark.parametrize("title", [
    "[BL] Sau Khi Trọng Sinh", "(Đam Mỹ) Thiếu Gia Và Vệ Sĩ", "đam mỹ - Tổng Tài Công", "Dam My Co Trang",
    "ĐM Xuyên Sách", "[đm] Trọng Sinh", "DM | Hiện Đại", "dm: Ngọt Sủng",
    "Boylove Hiện Đại", "Boy Love", "Boys Love", "Boy's Love Story", "BoyxBoy", "Boy x Boy", "BXB Novel",
    "Nam x Nam Cổ Đại", "NamxNam", "Danmei Collection", "Yaoi Doujin", "Shounen Ai",
    "Truyện Dammy Hiện Đại", "truyendammy", "ĐamMỹ Tổng Tài", "Đam-Mỹ", "Gay Romance",
    "Nhất Công Nhất Thụ", "Đam mĩ",
])
def test_bl_titles_are_blocked(title: str) -> None:
    assert find_blocked_title(title) is not None


@pytest.mark.parametrize("title", [
    "Blood Moon", "The Problem Child", "Fable", "Admin Của Tôi", "DMV Hell", "Đầm Dạ Hội",
    "Cô Gái Gầy Gò", "Tiếng Gáy Đêm", "Đàm Mỹ Linh", "Đại Chiến Công Thủ", "Công Chúa Và Thụ Phấn",
    "Tiểu Thuyết Hiện Đại", "Boyfriend", "Bleach", "Nam Nhi Chí Lớn", "Đấu Phá Thương Khung", "", None,
])
def test_normal_titles_are_not_blocked(title) -> None:
    assert find_blocked_title(title) is None
