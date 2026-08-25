#!/usr/bin/env python3

"""
模块化电子书读取与书名识别工具
- 支持用 Calibre 将各种电子书格式转换为 EPUB
- 提取 EPUB 纯文本
- 读取源书籍元信息（书名、作者、语言）
- 自动识别书中提到的其他书名（中文书名号 + 英文斜体）
- 输出书名、出现时的上下文片段与所在章节

依赖：
    - Calibre（提供 ebook-convert 命令行工具，用于格式转换）
    - Python 库：ebooklib, beautifulsoup4
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

try:
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub
except ImportError:
    print("缺少依赖库，请执行： pip install ebooklib beautifulsoup4 lxml")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent_temp.tools.common import DEFAULT_BOOK  # noqa: E402

# ======================================================================
# 常量：集中管理可调参数，避免代码中出现魔法数字
# ======================================================================
DEFAULT_CONTEXT_CHARS = 200     # 书名上下文前后各截取多少字符
MIN_TITLE_LEN = 2               # 合法书名的长度下限
MAX_TITLE_LEN = 80              # 合法书名的长度上限

# 中文书名号匹配（书名号内限制 1~60 字符）
TITLE_PATTERN = re.compile(r"《([^》]{1,60})》")

# 常见斜体标签（英文书名常用）
ITALIC_TAGS = ("i", "em", "cite", "dfn", "var")

# ebook-convert 常见安装路径（PATH 中找不到时的备用方案）
CALIBRE_CANDIDATES = (
    r"C:\Program Files\Calibre2\ebook-convert.exe",            # Windows
    r"C:\Program Files (x86)\Calibre2\ebook-convert.exe",      # Windows 32 位
    "/Applications/calibre.app/Contents/MacOS/ebook-convert",  # macOS
    "/usr/bin/ebook-convert",                                  # Linux
    "/usr/local/bin/ebook-convert",                            # Linux 常见
)



# ======================================================================
# 数据结构
# ======================================================================
@dataclass
class BookTitleMatch:
    """一条被识别出的书名，以及它的出处信息。"""

    title: str
    chapters: list[str] = field(default_factory=list)
    context: str = ""


class ReadBook:
    """电子书读取与书名识别。"""

    def __init__(self, calibre_convert_path: str | None = None):
        """
        初始化。

        :param calibre_convert_path: 手动指定 ebook-convert 的完整路径；
            为 None 时自动从 PATH 或常见安装位置查找
            （惰性查找，仅在实际需要格式转换时才定位）。
        """
        self._calibre_convert_custom = calibre_convert_path
        self._calibre_convert: str | None = None
        # 缓存最近一次打开的 EPUB，避免同一本书被重复解析（仅缓存最后一本）
        self._epub_cache_path: str | None = None
        self._epub_cache: epub.EpubBook | None = None

    # ------------------------------------------------------------------
    # Calibre 路径定位
    # ------------------------------------------------------------------
    def _get_calibre_convert(self) -> str:
        """返回 ebook-convert 路径（首次调用时查找并缓存）。"""
        if self._calibre_convert is None:
            self._calibre_convert = self._find_calibre_convert(
                self._calibre_convert_custom
            )
        return self._calibre_convert

    @staticmethod
    def _find_calibre_convert(custom_path: str | None) -> str:
        """定位 ebook-convert 可执行文件：自定义路径 > PATH > 常见安装路径。"""
        if custom_path:
            if os.path.exists(custom_path):
                return custom_path
            raise FileNotFoundError(f"指定的 ebook-convert 路径不存在：{custom_path}")

        found = shutil.which("ebook-convert")
        if found:
            return found

        for path in CALIBRE_CANDIDATES:
            if os.path.exists(path):
                return path

        raise RuntimeError(
            "未找到 ebook-convert，请先安装 Calibre 并确保它在 PATH 中，"
            "或通过参数 calibre_convert_path 指定其完整路径。"
        )

    # ------------------------------------------------------------------
    # 内部通用辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _is_epub(file_path: str) -> bool:
        """判断文件扩展名是否为 .epub。"""
        return Path(file_path).suffix.lower() == ".epub"

    @staticmethod
    def _is_valid_title(title: str) -> bool:
        """判断书名长度是否在合理范围内。"""
        return MIN_TITLE_LEN <= len(title) <= MAX_TITLE_LEN

    def _prepare_epub(
        self,
        input_path: str,
        output_epub: str | None = None,
        force_convert: bool = False,
    ) -> str:
        """确保输入是 EPUB；否则调用 Calibre 转换，返回可读取的 EPUB 路径。"""
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"文件不存在：{input_path}")

        if self._is_epub(input_path) and not force_convert:
            return input_path
        return self.convert_to_epub(input_path, output_epub)

    def _iter_documents(
        self, epub_path: str
    ) -> Iterator[tuple[BeautifulSoup, object]]:
        """遍历 EPUB 中所有文档节点，产出 (BeautifulSoup, item) 对。"""
        book = self._open_epub(epub_path)
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            yield soup, item

    def _open_epub(self, epub_path: str) -> epub.EpubBook:
        """打开 EPUB 并缓存最近一次结果（同一本书连续读取时避免重复解压）。"""
        if self._epub_cache_path != epub_path:
            self._epub_cache = epub.read_epub(epub_path)
            self._epub_cache_path = epub_path
        return self._epub_cache

    # ------------------------------------------------------------------
    # 源书籍元信息（书名、作者等）
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_metadata(
        book: epub.EpubBook,
    ) -> dict[str, list[tuple[str, dict]]]:
        """
        把 ebooklib 的 metadata 归一化为 {字段名: [(值, 属性)]}。

        ebooklib 0.18+ 的 metadata 键是命名空间 URI（如
        http://purl.org/dc/elements/1.1/），值为 {字段名: [(值, 属性)]}；
        旧版本可能是 ('DC', 'title') 或 'title' 形式，这里统一处理。
        """
        fields: dict[str, list[tuple[str, dict]]] = {}
        for key, value in (book.metadata or {}).items():
            if isinstance(key, str) and key.startswith("http"):
                items = value if isinstance(value, dict) else {}
                for name, entries in items.items():
                    fields.setdefault(name, []).extend(entries or [])
            elif isinstance(key, tuple) and len(key) == 2:
                fields.setdefault(key[1], []).extend(value or [])
            elif isinstance(key, str):
                fields.setdefault(key, []).extend(value or [])
        return fields

    @staticmethod
    def _first_metadata_value(entries: list) -> str | None:
        """取元数据字段第一个非空值；无则返回 None。"""
        for value, _ in entries or []:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _all_metadata_values(entries: list) -> list[str]:
        """收集字段全部非空值，按常见分隔符拆分并去重（保留首次出现顺序）。"""
        values: list[str] = []
        seen: set[str] = set()
        for value, _ in entries or []:
            if not isinstance(value, str) or not value.strip():
                continue
            for part in re.split(r"[;；、]", value):
                part = part.strip()
                if part and part not in seen:
                    seen.add(part)
                    values.append(part)
        return values

    def read_book_info(
        self,
        input_path: str,
        output_epub: str | None = None,
        force_convert: bool = False,
    ) -> dict[str, object]:
        """
        读取源电子书的元信息：书名、作者（以及语言、标识符）。

        书名缺失时回退为 EPUB 文件名；作者可能为多个（合著/署名并列）。

        :return: {"title", "authors", "language", "identifier"}
        """
        epub_path = self._prepare_epub(input_path, output_epub, force_convert)
        fields = self._normalize_metadata(self._open_epub(epub_path))

        title = self._first_metadata_value(fields.get("title"))
        if not title:
            title = Path(epub_path).stem

        return {
            "title": title,
            "authors": self._all_metadata_values(fields.get("creator")),
            "language": self._first_metadata_value(fields.get("language")),
            "identifier": self._first_metadata_value(fields.get("identifier")),
        }

    def _get_chapter_title(self, soup: BeautifulSoup, item: object) -> str:
        """从文档节点提取章标题，优先级：h1-h6 > <title> > 文件名。"""
        for tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            heading = soup.find(tag)
            if heading:
                title = heading.get_text(strip=True)
                if title:
                    return title

        if soup.title:
            title = soup.title.get_text(strip=True)
            if title:
                return title

        filename = getattr(item, "file_name", None) or item.get_name()
        return os.path.basename(filename)

    # ------------------------------------------------------------------
    # 格式转换与文本提取
    # ------------------------------------------------------------------
    def convert_to_epub(
        self, input_path: str, output_path: str | None = None
    ) -> str:
        """
        使用 Calibre 将电子书转换为 EPUB。

        :param input_path:  源电子书文件路径
        :param output_path: 输出 EPUB 路径，默认与源文件同目录同名
        :return: 转换后的 EPUB 文件路径
        """
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"输入文件不存在：{input_path}")

        if output_path is None:
            output_path = os.path.splitext(input_path)[0] + ".epub"

        # 避免将 EPUB“转换”成自身
        if Path(input_path).resolve() == Path(output_path).resolve():
            return input_path

        cmd = [self._get_calibre_convert(), input_path, output_path]
        print(f"正在执行转换：{' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception as exc:
            raise RuntimeError(f"调用 Calibre 失败：{exc}") from exc

        if result.returncode != 0:
            print("Calibre 转换出错：")
            print(result.stdout)
            print(result.stderr)
            raise RuntimeError("电子书转换失败，请检查日志信息。")

        if not os.path.exists(output_path):
            raise RuntimeError("转换后未生成目标 EPUB 文件")

        print(f"转换成功：{output_path}")
        return output_path

    def extract_epub_text(
        self, epub_path: str, max_chars: int | None = None
    ) -> str:
        """提取 EPUB 纯文本；max_chars 限制返回字符数（默认全部）。"""
        if not os.path.exists(epub_path):
            raise FileNotFoundError(f"EPUB 文件不存在：{epub_path}")

        parts = [
            soup.get_text("\n", strip=True)
            for soup, _ in self._iter_documents(epub_path)
        ]
        full_text = "\n\n".join(parts)

        if max_chars and len(full_text) > max_chars:
            return full_text[:max_chars] + "\n...... [已截断]"
        return full_text

    def read(
        self,
        input_path: str,
        max_chars: int | None = None,
        output_epub: str | None = None,
        force_convert: bool = False,
    ) -> str:
        """读取任意支持的电子书并返回纯文本内容。"""
        epub_path = self._prepare_epub(input_path, output_epub, force_convert)
        return self.extract_epub_text(epub_path, max_chars=max_chars)

    # ------------------------------------------------------------------
    # 书名识别（简单列表）
    # ------------------------------------------------------------------
    def find_book_titles(
        self,
        input_path: str,
        output_epub: str | None = None,
        force_convert: bool = False,
    ) -> list[str]:
        """查找书中提到的其他书名，返回去重（保留首次出现顺序）的书名列表。"""
        epub_path = self._prepare_epub(input_path, output_epub, force_convert)

        titles: list[str] = []
        seen: set[str] = set()
        for soup, _ in self._iter_documents(epub_path):
            text = soup.get_text("\n", strip=True)
            for title, _ in self._find_book_candidates(soup, text):
                if title not in seen:
                    seen.add(title)
                    titles.append(title)
        return titles

    # ------------------------------------------------------------------
    # 书名识别（带上下文与章节）
    # ------------------------------------------------------------------
    def find_book_titles_with_context(
        self,
        input_path: str,
        output_epub: str | None = None,
        force_convert: bool = False,
        context_chars: int = DEFAULT_CONTEXT_CHARS,
    ) -> list[dict[str, str]]:
        """
        查找书中提到的其他书名，并附带出现的上下文片段与所在章节。

        :return: 列表，元素形如 {"title", "context", "chapter"}
        """
        epub_path = self._prepare_epub(input_path, output_epub, force_convert)

        # 以书名为键聚合出处信息（保留首次出现顺序）
        matches: dict[str, BookTitleMatch] = {}
        for soup, item in self._iter_documents(epub_path):
            chapter = self._get_chapter_title(soup, item)
            text = soup.get_text("\n", strip=True)

            for title, pos in self._find_book_candidates(soup, text):
                match = matches.setdefault(title, BookTitleMatch(title=title))
                if chapter not in match.chapters:
                    match.chapters.append(chapter)
                if not match.context:
                    match.context = self._extract_context(
                        text, pos, len(title), context_chars
                    )

        return [
            {
                "title": match.title,
                "chapter": "；".join(match.chapters),
                "context": match.context,
            }
            for match in matches.values()
        ]

    # ------------------------------------------------------------------
    # 书名识别：内部实现细节
    # ------------------------------------------------------------------
    def _find_book_candidates(
        self, soup: BeautifulSoup, text: str
    ) -> list[tuple[str, int]]:
        """
        收集一段文本中的全部书名候选。

        :return: [(书名, 在文本中的位置)]；位置为 -1 表示未能定位
                 （如斜体文本在 HTML 中被拆成多段时）。
        """
        candidates: list[tuple[str, int]] = []

        # 1. 中文书名号
        for match in TITLE_PATTERN.finditer(text):
            title = match.group(1).strip()
            if self._is_valid_title(title):
                candidates.append((title, match.start()))

        # 2. 英文斜体
        for tag in ITALIC_TAGS:
            for elem in soup.find_all(tag):
                title = elem.get_text(strip=True).strip()
                if not self._is_valid_title(title):
                    continue
                pos = text.find(title)
                candidates.append((title, pos if pos != -1 else -1))

        return candidates

    @staticmethod
    def _extract_context(
        text: str, pos: int, title_len: int, context_chars: int
    ) -> str:
        """截取书名附近的上下文（前后各 context_chars 字符），截断处用省略号标记。"""
        if pos < 0:
            return ""

        start = max(0, pos - context_chars)
        end = min(len(text), pos + title_len + context_chars)
        context = text[start:end]

        if start > 0:
            context = "..." + context
        if end < len(text):
            context = context + "..."
        return context


# ======================================================================
# 命令行入口
# ======================================================================
def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="模块化电子书读取与书名识别",
        epilog="示例：\n"
               "  python read_book.py book.mobi --find-titles\n"
               "  python read_book.py book.epub --find-titles --json-output\n"
               "  python read_book.py book.epub --book-info\n"
               "  python read_book.py book.epub --book-info --find-titles --json-output",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=str(DEFAULT_BOOK),
        help=f"电子书文件路径（默认：{DEFAULT_BOOK}）",
    )
    parser.add_argument("-n", "--max-chars", type=int, default=None, help="只显示前 N 个字符")
    parser.add_argument("-o", "--output-epub", help="转换后的 EPUB 路径（可选）")
    parser.add_argument("--force-convert", action="store_true", help="即使输入是 EPUB 也强制转换")
    parser.add_argument("--calibre-path", default=None, help="ebook-convert 的完整路径（可选）")
    parser.add_argument("--book-info", action="store_true", help="输出源书籍元信息（书名、作者、语言）")
    parser.add_argument("--find-titles", action="store_true", help="查找书中提到的其他书名")
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="以 JSON 格式输出书名、上下文和出处（配合 --find-titles 使用）",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # 无参数直接运行时，默认执行“书名识别 + JSON 输出”，便于调试
    if not (args.find_titles or args.book_info or args.max_chars or args.output_epub):
        args.find_titles = True
        args.json_output = True

    reader = ReadBook(calibre_convert_path=args.calibre_path)

    source_info = None
    if args.book_info:
        source_info = reader.read_book_info(
            args.input,
            output_epub=args.output_epub,
            force_convert=args.force_convert,
        )

    if args.find_titles:
        if args.json_output:
            results = reader.find_book_titles_with_context(
                args.input,
                output_epub=args.output_epub,
                force_convert=args.force_convert,
                context_chars=DEFAULT_CONTEXT_CHARS,
            )
            if source_info is not None:
                print(
                    json.dumps(
                        {"source_book": source_info, "mentions": results},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            titles = reader.find_book_titles(
                args.input,
                output_epub=args.output_epub,
                force_convert=args.force_convert,
            )
            if source_info is not None:
                print(f"📖 源书籍：{source_info['title']}")
                if source_info["authors"]:
                    print(f"   作者：{'、'.join(source_info['authors'])}")
            print("\n📖 识别到的其他书名：")
            for i, title in enumerate(titles, 1):
                print(f"{i}. {title}")
        return

    if source_info is not None:
        if args.json_output:
            print(json.dumps(source_info, ensure_ascii=False, indent=2))
        else:
            print(f"📖 源书籍：{source_info['title']}")
            if source_info["authors"]:
                print(f"   作者：{'、'.join(source_info['authors'])}")
            if source_info["language"]:
                print(f"   语言：{source_info['language']}")
        return

    text = reader.read(
        args.input,
        max_chars=args.max_chars,
        output_epub=args.output_epub,
        force_convert=args.force_convert,
    )
    print(text)


if __name__ == "__main__":
    main()
