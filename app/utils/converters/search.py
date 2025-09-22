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

from app.domain.search import (
    SearchCondition,
    SearchMode,
    SearchParameters,
    SearchResult,
)
from app.web.vo import (
    ConditionOperator,
    SearchRequest,
    SearchResponse,
    SearchType,
    StructuredSearchResult,
    VectorHybridSearchResult,
)


class SearchConverter:
    """搜索数据转换器"""

    @staticmethod
    def request_vo_to_domain(request: SearchRequest) -> SearchParameters:
        """VO转Domain"""

        if request.type == SearchType.VECTOR_HYBRID:
            # 向量混合：生成双条件
            conditions: list[SearchCondition] = []
            for cond in request.query.conditions:
                # 文本搜索条件
                conditions.append(
                    SearchCondition(
                        field_name=cond.field,
                        mode=SearchMode.MATCH,
                        value=cond.value,
                    )
                )
                # 向量搜索条件（value还是文本）
                conditions.append(
                    SearchCondition(
                        field_name=f"{cond.field}_vector",
                        mode=SearchMode.VECTOR,
                        value=cond.value,
                    )
                )
        else:
            # 结构化搜索：直接映射
            conditions = [
                SearchCondition(
                    field_name=cond.field,
                    mode=SearchMode.TERM
                    if cond.op == ConditionOperator.TERM
                    else SearchMode.MATCH,
                    value=cond.value,
                )
                for cond in request.query.conditions
            ]

        return SearchParameters(
            index_name=request.query.index,
            conditions=conditions,
            limit=request.top_k,
            filters=request.query.filters,
        )

    @staticmethod
    def result_domain_to_vo(
        search_result: SearchResult, search_type: SearchType
    ) -> SearchResponse:
        """Domain转VO"""
        results: list[VectorHybridSearchResult | StructuredSearchResult]

        if search_type == SearchType.VECTOR_HYBRID:
            results = [
                VectorHybridSearchResult(
                    text=doc.content.get("text", ""),
                    file_metadata_id=doc.content.get("file_metadata_id", ""),
                    score=doc.score,
                )
                for doc in search_result.documents
            ]
        else:
            results = [
                StructuredSearchResult(
                    id=doc.id,
                    document=doc.content,
                    score=doc.score,
                )
                for doc in search_result.documents
                if doc.id
            ]

        return SearchResponse(type=search_type, results=results)
