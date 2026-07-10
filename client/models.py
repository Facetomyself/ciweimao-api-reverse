"""数据模型：Book, Division, Chapter。"""

from dataclasses import dataclass, field


@dataclass
class Chapter:
    """单章信息。"""
    chapter_id: str = ""
    chapter_index: int = 0
    chapter_title: str = ""
    word_count: int = 0
    is_vip: bool = False
    auth_access: bool = False
    content: str = ""          # 解密后的正文


@dataclass
class Division:
    """分卷。"""
    division_id: str = ""
    division_name: str = ""
    chapters: list = field(default_factory=list)


@dataclass
class Book:
    """书籍信息。"""
    book_id: str = ""
    book_name: str = ""
    author_name: str = ""
    cover_url: str = ""
    total_word_count: int = 0
    category_name: str = ""
    description: str = ""
    divisions: list = field(default_factory=list)

    @property
    def safe_name(self) -> str:
        """返回安全的文件名。"""
        import re
        return re.sub(r'[\\/:*?"<>|]', '', self.book_name)
