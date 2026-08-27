"""read_book 正文过滤单测:涟漪只取正文提及(body_only=True)。

对应 app/ai_assistant/tools/read_book.py:
- is_non_body_chapter:章节标题分类(前言/序言/尾记/附录等为非正文,
  序章/楔子/尾声等叙事性开头为正文);
- find_book_titles_with_context(body_only=True):在按书名聚合前剔除
  非正文章节的提及,使同一本书在正文+非正文都出现时只保留正文出处。
用临时生成的 EPUB 验证,不依赖真实书籍文件。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ebooklib import epub

from app.ai_assistant.tools.read_book import ReadBook, is_non_body_chapter


class NonBodyChapterTest(unittest.TestCase):
    """is_non_body_chapter 的章节标题分类。"""

    def test_body_chapters_kept(self) -> None:
        for chapter in (
            "第一章",
            "第一章 风起",
            "第1章",
            "1",
            "序章",
            "序幕",
            "楔子",
            "尾声",
            "引子",
            "第二部 三体问题",
            "Part I",
            "",
        ):
            self.assertFalse(is_non_body_chapter(chapter), chapter)

    def test_non_body_chapters_filtered(self) -> None:
        for chapter in (
            "前言",
            "序",
            "序一",
            "序：给读者",
            "自序",
            "代序",
            "序言",
            "译者序",
            "译序",
            "编者按",
            "编者的话",
            "出版说明",
            "出版者的话",
            "导读",
            "引言",
            "开场白",
            "凡例",
            "内容简介",
            "目录",
            "题记",
            "后记",
            "跋",
            "附录",
            "注释",
            "尾注",
            "致谢",
            "译后记",
            "作者的话",
            "参考文献",
            "索引",
            "年表",
            "大事记",
            "Foreword",
            "Introduction",
            "Afterword",
            "Appendix",
            "Acknowledgements",
            "Bibliography",
            "Index",
        ):
            self.assertTrue(is_non_body_chapter(chapter), chapter)

    def test_none_kept(self) -> None:
        self.assertFalse(is_non_body_chapter(None))


def _make_epub(path: Path) -> None:
    """生成测试 EPUB:前言(白鲸) + 第一章(挪威的森林、白鲸) + 后记(海边的卡夫卡)。"""
    book = epub.EpubBook()
    book.set_identifier("body-filter-test")
    book.set_title("测试之书")
    book.set_language("zh")
    book.add_author("测试作者")

    preface = epub.EpubHtml(title="前言", file_name="preface.xhtml", lang="zh")
    preface.content = (
        "<html><body><h1>前言</h1>"
        "<p>译者序中曾提到《白鲸》这部作品。</p></body></html>"
    )
    chapter = epub.EpubHtml(title="第一章", file_name="chap_1.xhtml", lang="zh")
    chapter.content = (
        "<html><body><h1>第一章</h1>"
        "<p>正文提到《挪威的森林》,也提到《白鲸》。</p></body></html>"
    )
    afterword = epub.EpubHtml(title="后记", file_name="afterword.xhtml", lang="zh")
    afterword.content = (
        "<html><body><h1>后记</h1>"
        "<p>后记提到《海边的卡夫卡》。</p></body></html>"
    )

    for item in (preface, chapter, afterword):
        book.add_item(item)
    book.toc = (preface, chapter, afterword)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", preface, chapter, afterword]
    epub.write_epub(str(path), book)


class BodyOnlyFilterTest(unittest.TestCase):
    """find_book_titles_with_context(body_only=True) 集成验证。"""

    def test_mentions_only_from_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "test.epub"
            _make_epub(book)
            reader = ReadBook()
            all_mentions = reader.find_book_titles_with_context(str(book))
            body_only = reader.find_book_titles_with_context(str(book), body_only=True)

        titles_all = {m["title"] for m in all_mentions}
        titles_body = {m["title"] for m in body_only}
        self.assertEqual(titles_all, {"白鲸", "挪威的森林", "海边的卡夫卡"})
        self.assertEqual(titles_body, {"白鲸", "挪威的森林"})

    def test_mixed_chapter_aggregates_body_only(self) -> None:
        """同一本书在前言与正文都出现:body_only 只保留正文章节与证据出处。"""
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "test.epub"
            _make_epub(book)
            reader = ReadBook()
            body_only = reader.find_book_titles_with_context(str(book), body_only=True)

        whale = next(m for m in body_only if m["title"] == "白鲸")
        self.assertEqual(whale["chapter"], "第一章")  # 前言出处已被剔除
        self.assertNotIn("前言", whale["chapter"])
        self.assertNotIn("译者序", whale["context"])


if __name__ == "__main__":
    unittest.main()
