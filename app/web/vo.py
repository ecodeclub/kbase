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

"""Web层VO模型定义"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, Json, field_validator
from pydantic_core.core_schema import ValidationInfo

from app.config.settings import settings


class FileUploadResponse(BaseModel):
    """文件上传后的标准响应模型"""

    task_id: str = Field(
        ..., description="本次上传任务的唯一ID，用于追踪和调试"
    )
    message: str = Field(
        "文件已接收，正在后台处理中...", description="操作结果信息"
    )


class UrlUploadRequest(BaseModel):
    """从URL上传的请求体模型"""

    url: HttpUrl = Field(..., description="要下载和索引的文件的完整URL")
    index_prefix: str = Field(..., min_length=1, description="索引完整名称前缀")


class UrlUploadResponse(BaseModel):
    """从URL上传后的标准响应模型"""

    task_id: str = Field(
        ..., description="本次上传任务的唯一ID，用于追踪和调试"
    )
    message: str = Field(
        "URL已接收，正在后台下载和处理中...", description="操作结果信息"
    )


class SearchType(str, Enum):
    """搜索类型"""

    VECTOR_HYBRID = "vector_hybrid"  # 向量+全文混合搜索
    STRUCTURED = "structured"  # 结构化条件搜索


class ConditionOperator(str, Enum):
    """搜索条件操作符"""

    TERM = "term"  # 精确匹配
    MATCH = "match"  # 全文搜索匹配


class Condition(BaseModel):
    """搜索条件"""

    field: str = Field(..., min_length=1, description="文档中的字段名称")
    op: ConditionOperator = Field(
        ..., description="操作符：term(精确匹配) 或 match(全文搜索)"
    )
    value: str | int | float | bool = Field(
        ..., description="字段值，支持多种类型"
    )

    @field_validator("value")
    @classmethod
    def validate_value_not_empty_string(
        cls, v: str | int | float | bool
    ) -> str | int | float | bool:
        """验证字符串值不能为空"""
        if isinstance(v, str) and v.strip() == "":
            raise ValueError("字符串类型的查询值不能为空")
        return v


class Query(BaseModel):
    """查询对象"""

    index: str = Field(..., min_length=1, description="ES索引名称")
    conditions: list[Condition] = Field(
        ..., min_length=1, description="搜索条件列表，至少需要一个条件"
    )
    filters: dict[str, Any] | None = Field(
        None, description="过滤条件，用于精确过滤不参与计分"
    )


class SearchRequest(BaseModel):
    """搜索请求"""

    type: SearchType = Field(..., description="搜索类型")
    query: Query = Field(..., description="查询条件")
    top_k: int = Field(
        ...,
        ge=1,
        le=settings.search.max_top_k,
        description="返回结果数量 1 <= top_k <= 配置文件中的max_top_k",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: Query, info: ValidationInfo) -> Query:
        """根据搜索类型验证查询条件"""
        search_type = info.data.get("type")

        if search_type == SearchType.VECTOR_HYBRID:
            if (
                len(v.conditions) != 1
                or v.conditions[0].op != ConditionOperator.MATCH
            ):
                raise ValueError(
                    "vector_hybrid 模式只能有一个 match 类型的搜索条件"
                )

        return v


class ESSearchRequest(BaseModel):
    index: str = Field(..., min_length=1, description="ES索引名称")
    query: dict[str, Any] = Field(..., description="符合ES语法规范的查询语句")


class VectorHybridSearchResult(BaseModel):
    """向量+全文混合搜索结果"""

    text: str = Field(..., description="文档内容")
    file_metadata_id: str = Field(..., description="文件元数据ID")
    score: float = Field(..., description="相关度分数")


class StructuredSearchResult(BaseModel):
    """结构化搜索结果"""

    id: str = Field(..., description="文档唯一标识符")
    document: dict[str, Any] = Field(..., description="文档数据")
    score: float = Field(..., description="相关度分数")


class SearchResponse(BaseModel):
    """搜索响应"""

    results: list[VectorHybridSearchResult | StructuredSearchResult] = Field(
        default_factory=list, description="搜索结果"
    )


class SaveRequest(BaseModel):
    """
    Elasticsearch文档保存请求模型

    以key为_id向名为index的索引中插入doc_json。
    如果key不存在则直接插入，如果key已存在则完整覆盖。

    Attributes:
        index: ES中索引的完整名称，假定mappings已建立好
        key: 文档的唯一标识，将作为ES中的_id使用
        doc_json: 满足JSON格式的字符串文档内容，会自动解析为字典
    """

    index: str = Field(..., min_length=1, description="ES索引名称")
    key: str = Field(..., min_length=1, description="文档唯一标识")
    doc_json: Json[dict[str, Any]] = Field(
        ..., description="JSON格式的文档内容"
    )


class SaveResponse(BaseModel):
    """文档保存操作的响应模型"""

    message: str = Field(default="操作成功", description="操作结果信息")
