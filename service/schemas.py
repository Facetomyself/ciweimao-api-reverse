"""FastAPI 请求模型与任务 payload 契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_RANKING_SPECS = (
    ("fans_value", "week"),
    ("fans_value", "month"),
    ("fans_value", "total"),
    ("no_vip_click", "week"),
    ("yp", "month"),
    ("word_count", "week"),
    ("track_read", "week"),
    ("complet", "month"),
    ("blade", "month"),
    ("yp_new", "month"),
    ("recommend", "total"),
    ("tsukkomi", "week"),
    ("favor", "week"),
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RankingSpec(StrictModel):
    order: str = Field(min_length=1, max_length=64)
    time_type: Literal["week", "month", "total"]

    @property
    def source_key(self) -> str:
        return f"{self.order}:{self.time_type}"


def default_ranking_specs() -> list[RankingSpec]:
    return [RankingSpec(order=order, time_type=time_type)
            for order, time_type in DEFAULT_RANKING_SPECS]


class DownloadByNameRequest(StrictModel):
    book_name: str = Field(min_length=1, max_length=200)
    author_name: str | None = Field(default=None, max_length=100)
    exact_match: bool = True
    max_search_pages: int = Field(default=5, ge=1, le=20)
    skip_existing: bool = True
    include_book_id: bool = True


class DownloadBookRequest(StrictModel):
    """由同步任务发现后按 book_id 投递的免费章节下载。"""

    book_id: str = Field(min_length=1, max_length=64)
    book_name: str = Field(default="", max_length=200)
    author_name: str = Field(default="", max_length=100)
    source: str = Field(default="sync_all", min_length=1, max_length=64)
    skip_existing: bool = True
    include_book_id: bool = True


class SyncRankingsRequest(StrictModel):
    specs: list[RankingSpec] = Field(
        default_factory=default_ranking_specs,
        min_length=1,
        max_length=50,
    )
    count: int = Field(default=10, ge=1, le=100)
    category_index: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def unique_specs(self):
        keys = [spec.source_key for spec in self.specs]
        if len(keys) != len(set(keys)):
            raise ValueError("榜单 specs 不得重复")
        return self


class SyncNewBooksRequest(StrictModel):
    max_pages: int = Field(default=1, ge=1, le=100)
    count: int = Field(default=100, ge=1, le=100)


class SyncAllRequest(StrictModel):
    """一次调度中顺序同步榜单和新书，共享同一个代理租约。"""

    rankings: SyncRankingsRequest = Field(
        default_factory=SyncRankingsRequest,
    )
    new_books: SyncNewBooksRequest = Field(
        default_factory=SyncNewBooksRequest,
    )


TaskStatus = Literal[
    "queued", "running", "succeeded", "failed", "cancelled",
]
