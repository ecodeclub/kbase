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

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchRequest:
    """封装搜索请求，新增 mode 和 filters。"""

    query: str
    top_k: int = 5
    filters: dict[str, Any] | None = field(default_factory=dict)


@dataclass
class ContextChunk:
    """定义一个上下文块，用于最终返回结果。"""

    text: str
    file_metadata_id: str
    score: float


@dataclass
class SearchResponse:
    """定义最终的搜索响应格式。"""

    context: list[ContextChunk]
