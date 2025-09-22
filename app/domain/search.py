# Copyright 2021 ecodeclub
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http:#www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from dataclasses import dataclass
from enum import Enum
from typing import Any


class SearchMode(str, Enum):
    """基础查询模式"""

    VECTOR = "vector"  # 向量搜索
    TERM = "term"  # 精确匹配
    MATCH = "match"  # 模糊匹配


@dataclass(frozen=True)
class SearchCondition:
    """搜索条件 - 值对象"""

    field_name: str
    mode: SearchMode
    value: str | int | float | bool


@dataclass(frozen=True)
class SearchParameters:
    """搜索参数 - 值对象"""

    index_name: str
    conditions: list[SearchCondition]
    limit: int = 10
    filters: dict[str, Any] | None = None


@dataclass
class DocumentResult:
    """文档结果 - 值对象"""

    content: dict[str, Any]
    score: float
    id: str | None = None


@dataclass
class SearchResult:
    """搜索结果 - 聚合根"""

    documents: list[DocumentResult]
    total_count: int
    search_time_ms: int

    def is_empty(self) -> bool:
        return len(self.documents) == 0
