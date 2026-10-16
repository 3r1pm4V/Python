"""Chạy từ thư mục gốc: python -m pytest -q tests"""
from __future__ import annotations

import unicodedata

from app_core.text_utils import (
    best_title_match, find_dam_my_tag, normalize_for_match, pick_epub_link,
)


def test_normalize_handles_missing_vietnamese_letters_and_nfd() -> None:
    assert normalize_for_match("Tĩnh Ũ-Đấu_Phá!!") == "tĩnh ũ đấu phá"  # bản cũ làm mất ĩ, ũ
    nfd = unicodedata.normalize("NFD", "Đấu Phá Thương Khung")
    assert normalize_for_match(nfd) == normalize_for_match("Đấu Phá Thương Khung")


def test_best_title_match_rules() -> None:
    idx = {"dau pha thuong khung tac gia": "long", "dau pha": "short", "a": "tiny"}
    assert best_title_match("dau pha", idx) == "short"          # khớp tuyệt đối
    assert best_title_match("thuong khung", idx) == "long"      # nằm trong tên có hậu tố tác giả
    assert best_title_match("xyz abc", idx) is None
    # khoá quá ngắn không được "nằm trong" mọi tiêu đề (bản cũ khớp nhầm)
    assert best_title_match("co dai nhat the", {"a": "tiny"}) is None
    # ranh giới từ: 'ha' không nằm trong 'pha'
    assert best_title_match("dau ph", {"dau pha": "x"}) is None


def test_best_title_match_prefers_closest_length() -> None:
    idx = {"dau pha thuong khung phan 2 ngoai truyen": "far", "dau pha thuong khung": "near"}
    assert best_title_match("dau pha thuong", idx) == "near"


def test_pick_epub_link_prefers_drive_and_accepts_internal_download() -> None:
    page = "https://dtv-ebook.com.vn/a_1.html"
    html = ('<a href="/download/abc">Tải</a><a href="#">epub</a>'
            '<a href="https://drive.google.com/file/d/XYZ/view">Drive</a>')
    assert pick_epub_link(html, page) == "https://drive.google.com/file/d/XYZ/view"
    # bản cũ so ".epub" (thường) với chuỗi đã upper() nên link nội bộ không bao giờ được nhận
    assert pick_epub_link('<a href="/download/abc">EPUB</a>', page) == "https://dtv-ebook.com.vn/download/abc"
    assert pick_epub_link('<a href="/tai/abc">EPUB</a>', page) is None
    assert pick_epub_link('<a href="javascript:void(0)">EPUB</a>', page) is None
    assert pick_epub_link("", page) is None


def test_dam_my_matches_whole_words_only() -> None:
    assert find_dam_my_tag(["blood", "problem", "fable", "romance"]) is None  # 'bl' không khớp nhầm
    assert find_dam_my_tag(["romance", "BL"]) == "BL"
    assert find_dam_my_tag(["Đam Mỹ"]) == "Đam Mỹ"
    assert find_dam_my_tag(["boys love", "x"]) == "boys love"
    assert find_dam_my_tag([]) is None
