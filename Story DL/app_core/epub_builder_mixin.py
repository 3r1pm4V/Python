"""Auto-split module — part of the StoryLoaderGUI refactor."""
from __future__ import annotations

from html import escape

import os
from pathlib import Path
from typing import List, Tuple, Optional

from ebooklib import epub

from app_core.constants import (
    INVALID_FS_CHARS_RE,
)


class EpubBuilderMixin:
    @staticmethod
    def _cover_filename(data: bytes) -> str:
        """Đặt đuôi file bìa theo nội dung thật (trước đây luôn .jpg kể cả PNG/WEBP/GIF)."""
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "cover.png"
        if data[:4] == b"GIF8":
            return "cover.gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "cover.webp"
        return "cover.jpg"

    def create_epub(
        self,
        story_name: str,
        chapters: List[Tuple[str, str]],
        dest_dir: Path,
        cover_image_data: Optional[bytes] = None,
        author: str = "",
    ) -> bool:
        """Tạo EPUB (ghi qua file .part rồi đổi tên). Trả True nếu thành công."""
        try:
            book = epub.EpubBook()
            book.set_title(story_name)
            book.set_language('vi')
            if author:
                book.add_author(author)

            if cover_image_data:
                book.set_cover(self._cover_filename(cover_image_data), cover_image_data)

            epub_chaps = []
            for i, (title, content) in enumerate(chapters, 1):
                title = title or f"Chương {i}"
                content = content or ""
                safe_title = escape(title)
                c = epub.EpubHtml(title=title, file_name=f'chap_{i}.xhtml', lang='vi')

                if content.strip().startswith("<") and ("</" in content or "/>" in content):
                    html_body = f"<h2>{safe_title}</h2>{content}"
                else:
                    html_body = f"<h2>{safe_title}</h2>"
                    for para in content.split('\n'):
                        if para.strip():
                            html_body += f"<p>{escape(para.strip())}</p>"

                c.content = html_body
                book.add_item(c)
                epub_chaps.append(c)

            book.toc = tuple(epub_chaps)
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            # set_cover() tạo trang bìa uid="cover"; gán lại spine mà thiếu nó thì bìa mất khỏi thứ tự đọc
            book.spine = (["cover"] if cover_image_data else []) + ["nav"] + epub_chaps

            safe_name = INVALID_FS_CHARS_RE.sub('_', story_name).strip() or "untitled"
            final_path = dest_dir / f"{safe_name}.epub"
            part_path = final_path.with_name(final_path.name + ".part")
            try:
                epub.write_epub(str(part_path), book, {})
                os.replace(part_path, final_path)
            finally:
                part_path.unlink(missing_ok=True)
            self.log(f"   ✅ Đã tạo EPUB: {story_name}")
            return True
        except Exception as e:
            self.log(f"   ❌ Lỗi tạo EPUB: {str(e)[:120]}")
            return False

    def extract_text_with_pseudo_elements(self, element) -> str:
        script = """
        function extractFullText(node) {
            if (!node) return '';
            document.body.offsetHeight;
            var text = '';
            if (node.nodeType === 1) {
                var beforeStyle = window.getComputedStyle(node, '::before');
                var beforeContent = beforeStyle.content;
                if (beforeContent && beforeContent !== 'none' && beforeContent !== 'normal') {
                    text += beforeContent.replace(/^["']|["']$/g, '');
                }
            }
            if (node.nodeType === 3) {
                text += node.textContent;
            } else if (node.nodeType === 1) {
                for (var i = 0; i < node.childNodes.length; i++) {
                    text += extractFullText(node.childNodes[i]);
                }
            }
            if (node.nodeType === 1) {
                var afterStyle = window.getComputedStyle(node, '::after');
                var afterContent = afterStyle.content;
                if (afterContent && afterContent !== 'none' && afterContent !== 'normal') {
                    text += afterContent.replace(/^["']|["']$/g, '');
                }
            }
            return text;
        }
        return extractFullText(arguments[0]);
        """
        try:
            driver = self.get_valid_driver()
            return driver.execute_script(script, element).strip()
        except Exception:
            return element.text.strip()

    @staticmethod
    def _extract_visible_paragraphs(container) -> List[str]:
        paragraphs = []
        for p in container.find_all("p"):
            style = p.get("style", "").lower()
            if "display: none" in style or "display:none" in style \
               or "visibility: hidden" in style or "visibility:hidden" in style \
               or "height: 0" in style or "height:0" in style:
                continue
            text = p.get_text("\n", strip=True)
            if text:
                paragraphs.append(text)
        return paragraphs

    def _select_first(self, soup_or_el, selector_list: List[str]):
        for sel in selector_list:
            try:
                el = soup_or_el.select_one(sel)
                if el:
                    return el
            except Exception:
                continue
        return None
