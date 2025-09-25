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

import logging
import os
import time
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from elastic_transport import ObjectApiResponse
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from langchain_core.documents import Document as LangChainDocument

from app.config.settings import Settings
from app.domain.document import Document
from app.domain.search import (
    DocumentResult,
    SearchCondition,
    SearchMode,
    SearchParameters,
    SearchResult,
)

logger = logging.getLogger(__name__)


class Loader(Protocol):
    """加载器接口，负责从源读取内容。"""

    @staticmethod
    def load(document: Document) -> list[LangChainDocument]: ...


class Splitter(Protocol):
    """分割器接口，负责将长文档切分为块。"""

    def split_documents(
        self, documents: list[LangChainDocument]
    ) -> list[LangChainDocument]: ...


class Embedder(Protocol):
    """嵌入模型接口，负责将文本转换为向量。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimensions(self) -> int: ...
    @property
    def similarity_metric(self) -> str: ...


class Reranker(Protocol):
    """重排器接口，负责对初步检索结果进行精排。"""

    def rerank(
        self, query: str, results: list[DocumentResult]
    ) -> list[DocumentResult]: ...


class ElasticsearchService:
    def __init__(
        self,
        client: Elasticsearch,
        loader: Loader,
        splitter: Splitter,
        embedder: Embedder,
        reranker: Reranker,
        settings: Settings,
    ) -> None:
        self._client = client
        self._loader = loader
        self._splitter = splitter
        self._embedder = embedder
        self._reranker = reranker
        self._settings = settings

    def _metadata_index_name(self, index_prefix: str) -> str:
        return index_prefix + self._settings.elasticsearch.metadata_index_suffix

    def _chunk_index_name(self, index_prefix: str) -> str:
        return index_prefix + self._settings.elasticsearch.chunk_index_suffix

    def _ensure_metadata_index_exists(self, metadata_index: str) -> None:
        """确保索引 metadata_index 存在"""
        if not self._client.indices.exists(index=metadata_index):
            body = {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "index": {
                        "max_result_window": 10000,
                        "refresh_interval": "1s",
                    },
                },
                "mappings": {
                    "properties": {
                        "name": {
                            "type": "text",
                            "analyzer": "ik_max_word",
                            "fields": {"keyword": {"type": "keyword"}},
                        },
                        "path": {"type": "keyword"},
                        "category": {"type": "keyword"},
                        "tags": {"type": "keyword"},
                        "size": {"type": "long"},
                        "total_chunks": {"type": "integer"},
                        "created_at": {
                            "type": "date",
                            "format": "epoch_millis",
                        },
                        "updated_at": {
                            "type": "date",
                            "format": "epoch_millis",
                        },
                    }
                },
            }

            try:
                self._client.indices.create(index=metadata_index, body=body)
            except Exception as e:
                raise e

    def _ensure_chunk_index_exists(self, chunk_index: str) -> None:
        """确保索引chunk_index存在"""
        if not self._client.indices.exists(index=chunk_index):
            body = {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "index": {
                        "max_result_window": 10000,
                        "refresh_interval": "1s",
                    },
                },
                "mappings": {
                    "properties": {
                        "file_metadata_id": {"type": "keyword"},
                        "content": {
                            "type": "text",
                            "analyzer": "ik_max_word",
                            "search_analyzer": "ik_smart",
                        },
                        "content_vector": {
                            "type": "dense_vector",
                            "dims": self._embedder.dimensions,
                            "similarity": self._embedder.similarity_metric,
                            "index": True,
                            "index_options": {
                                "type": self._settings.embedder.index_type,
                                "m": 32,
                                "ef_construction": 100,
                            },
                        },
                        "chunk_index": {"type": "integer"},
                        "position": {
                            "properties": {
                                "page_number": {"type": "integer"},
                                "start_char_index": {"type": "integer"},
                            }
                        },
                    }
                },
            }
            try:
                self._client.indices.create(index=chunk_index, body=body)
            except Exception as e:
                raise e

    def _ensure_indexes_exist(self, index_prefix: str) -> tuple[str, str]:
        """确保索引存在并返回索引名

        Args:
            index_prefix: 索引前缀

        Returns:
            tuple: (metadata_index, chunk_index)
        """
        metadata_index = self._metadata_index_name(index_prefix)
        chunk_index = self._chunk_index_name(index_prefix)

        self._ensure_metadata_index_exists(metadata_index)
        self._ensure_chunk_index_exists(chunk_index)

        return metadata_index, chunk_index

    def store_for_vector_hybrid_search(self, document: Document) -> str:
        """
        将文档存入双索引系统。
        1. 存储文件元数据到 file_metadatas。
        2. 切分文件为chunks，并将 chunks相关信息 及对应的源文件的 file_metadata_id 存入 file_chunks。
        :return: 在 file_metadatas 中生成的文档 ID。
        """

        metadata_index, chunk_index = self._ensure_indexes_exist(
            document.index_prefix
        )

        metadata_id = self._create_metadata(metadata_index, document)
        document.id = metadata_id  # 确保 document 对象持有 ID
        logger.info(f"元数据占位符创建成功，ID: {metadata_id}")

        try:
            # 尝试创建和存储 chunks。失败会抛出异常。
            created_chunks_count = self._create_chunks(chunk_index, document)
            logger.info(f"成功存储 {created_chunks_count} 个文档块。")

            # Chunks 存储成功后，才更新元数据中的 total_chunks
            now_millis = int(datetime.now(UTC).timestamp() * 1000)
            self._client.update(
                index=metadata_index,
                id=metadata_id,
                body={
                    "doc": {
                        "total_chunks": created_chunks_count,
                        "updated_at": now_millis,
                    }
                },
                refresh="wait_for",
            )
            logger.info(
                f"元数据更新成功，total_chunks 已写入: {created_chunks_count}。"
            )
            self._client.indices.refresh(index=chunk_index)
            return metadata_id

        except Exception as e:
            # 如果上述 try 块中任何一步失败，执行回滚操作
            logger.error(f"文档处理失败，错误: {e}。正在回滚元数据...")
            self._client.delete(
                index=metadata_index, id=metadata_id, refresh=True
            )
            logger.info(f"元数据 {metadata_id} 已被成功删除。")
            # 重新抛出异常，让上层调用者知道操作失败
            raise RuntimeError("文档存储失败，已回滚。") from e

    def _create_metadata(self, metadata_index: str, document: Document) -> str:
        """
        根据文档创建并存储元数据索引数据
        :return: 在 file_metadatas 中生成的文档 ID。
        """
        now_millis = int(datetime.now(UTC).timestamp() * 1000)
        doc = {
            "name": os.path.basename(document.path),
            "path": document.path,
            "category": document.category,
            "tags": document.tags,
            "size": document.size,
            "total_chunks": 0,
            "created_at": now_millis,
            "updated_at": now_millis,
        }
        meta_response = self._client.index(
            index=metadata_index, document=doc, refresh="wait_for"
        )
        return str(meta_response["_id"])

    def _create_chunks(self, chunk_index: str, document: Document) -> int:
        """增强错误处理，支持部分回滚"""
        if not document.id:
            raise ValueError("文档ID未设置")

        chunks = self._splitter.split_documents(self._loader.load(document))
        if not chunks:
            raise RuntimeError("未提取出任何文本块")

        content_vectors = self._embedder.embed_documents(
            [chunk.page_content for chunk in chunks]
        )

        chunk_docs = []
        chunk_ids = []  # 记录已创建的chunk IDs

        try:
            for i, (chunk, content_vector) in enumerate(
                zip(chunks, content_vectors, strict=True)
            ):
                doc = {
                    "_index": chunk_index,
                    "_id": f"{document.id}_{i}",
                    "file_metadata_id": document.id,
                    "content": chunk.page_content,
                    "content_vector": content_vector,
                    "chunk_index": i,
                    "position": {
                        "page_number": chunk.metadata.get("page"),
                        "start_char_index": chunk.metadata.get("start_index"),
                    },
                }
                chunk_docs.append(doc)
                chunk_ids.append(str(doc["_id"]))

            success, failed = bulk(
                client=self._client,
                actions=chunk_docs,
                stats_only=False,
                raise_on_error=False,
            )

            if failed:
                # 清理已成功写入的chunks
                self._cleanup_chunks(chunk_index, chunk_ids[:success])
                raise RuntimeError(f"批量写入失败: {failed}")

            return success

        except Exception:
            # 确保清理所有可能已写入的chunks
            if chunk_ids:
                self._cleanup_chunks(chunk_index, chunk_ids)
            raise

    def _cleanup_chunks(self, chunk_index: str, chunk_ids: list[str]) -> None:
        """清理指定的chunks"""
        for chunk_id in chunk_ids:
            try:
                self._client.delete(index=chunk_index, id=chunk_id)
            except Exception as e:
                logger.error(f"删除文档分失败，错误: {e}。")
                pass

    def search(self, parameters: SearchParameters) -> SearchResult:
        """
        执行搜索 - 支持多种搜索模式

        Args:
            parameters: 搜索参数，包含索引、条件、限制等

        Returns:
            SearchResult: 统一的搜索结果
        """
        start_time = time.time()

        # 按搜索模式分类条件
        search_conditions = self._classify_conditions(parameters.conditions)

        # 根据条件类型构建查询
        if search_conditions["vector"] and search_conditions["match"]:
            # 向量+全文混合搜索（兼容旧版本）
            search_body = self._build_hybrid_search_body(
                parameters, search_conditions
            )
        else:
            # 纯结构化搜索（新版本）
            search_body = self._build_structured_search_body(
                parameters, search_conditions
            )

        # 执行ES搜索
        response = self._client.search(
            index=parameters.index_name, body=search_body
        )

        # 计算搜索耗时
        search_time_ms = int((time.time() - start_time) * 1000)

        # 转换为Domain对象并返回
        return self._convert_to_search_result(
            response, search_time_ms, parameters.limit, search_conditions
        )

    @staticmethod
    def _classify_conditions(
        conditions: list[SearchCondition],
    ) -> dict[str, list[SearchCondition]]:
        """
        按搜索模式分类条件

        Args:
            conditions: 搜索条件列表

        Returns:
            分类后的条件字典
        """
        classified: dict[str, list[SearchCondition]] = {
            "vector": [],
            "match": [],
            "term": [],
        }

        for condition in conditions:
            if condition.mode == SearchMode.VECTOR:
                classified["vector"].append(condition)
            elif condition.mode == SearchMode.MATCH:
                classified["match"].append(condition)
            elif condition.mode == SearchMode.TERM:
                classified["term"].append(condition)

        return classified

    def _build_hybrid_search_body(
        self,
        parameters: SearchParameters,
        search_conditions: dict[str, list[SearchCondition]],
    ) -> dict[str, Any]:
        """
        构建向量+全文混合搜索查询体（兼容旧版本）

        Args:
            parameters: 搜索参数
            search_conditions: 分类后的搜索条件

        Returns:
            ES查询体
        """
        # 获取文本查询进行向量化
        text_query: str | None = None
        for condition in search_conditions["vector"]:
            if isinstance(condition.value, str):
                text_query = condition.value
        if not text_query:
            raise ValueError("向量混合搜索需要文本查询内容")

        # 生成查询向量
        query_vector = self._embedder.embed_documents([text_query])[0]

        # 计算召回数量（用于后续重排序）
        retrieval_size = parameters.limit * self._settings.retrieval.multiplier

        # 获取权重配置
        vector_weight = self._settings.retrieval.vector_weight
        text_weight = self._settings.retrieval.text_weight

        # 构建混合搜索查询体
        search_body: dict[str, Any] = {
            "size": retrieval_size,
            "_source": ["content", "file_metadata_id"],  # 只返回需要的字段
            "knn": {
                "field": "content_vector",  # 固定向量字段
                "query_vector": query_vector,
                "k": retrieval_size,
                "num_candidates": 100,
                "boost": vector_weight,
            },
            "query": {
                "bool": {
                    "should": [
                        # 普通匹配
                        {
                            "match": {
                                "content": {
                                    "query": text_query,
                                    "boost": text_weight * 0.5,
                                }
                            }
                        },
                        # 短语匹配
                        {
                            "match_phrase": {
                                "content": {
                                    "query": text_query,
                                    "boost": text_weight * 0.3,
                                }
                            }
                        },
                    ],
                    "minimum_should_match": 0,
                }
            },
        }

        # 添加过滤条件
        if parameters.filters:
            # 为knn查询添加过滤器
            search_body["knn"]["filter"] = parameters.filters
            # 为全文查询添加过滤器
            search_body["query"]["bool"]["filter"] = parameters.filters

        return search_body

    @staticmethod
    def _build_structured_search_body(
        parameters: SearchParameters,
        search_conditions: dict[str, list[SearchCondition]],
    ) -> dict[str, Any]:
        """
        构建结构化搜索查询体（新版本）

        Args:
            parameters: 搜索参数
            search_conditions: 分类后的搜索条件

        Returns:
            ES查询体
        """
        bool_query: dict[str, Any] = {"bool": {"must": []}}

        # 添加MATCH查询条件
        for condition in search_conditions["match"]:
            bool_query["bool"]["must"].append(
                {"match": {condition.field_name: {"query": condition.value}}}
            )

        # 添加TERM查询条件
        for condition in search_conditions["term"]:
            bool_query["bool"]["must"].append(
                {"term": {condition.field_name: condition.value}}
            )

        search_body: dict[str, Any] = {
            "size": parameters.limit,
            "query": bool_query,
        }

        # 添加过滤条件
        if parameters.filters:
            bool_query["bool"]["filter"] = parameters.filters

        return search_body

    def _convert_to_search_result(
        self,
        response: ObjectApiResponse[Any],
        search_time_ms: int,
        limit: int,
        search_conditions: dict[str, list[SearchCondition]],
    ) -> SearchResult:
        """
        将ES响应转换为Domain搜索结果

        Args:
            response: ES查询响应
            search_time_ms: 搜索耗时（毫秒）
            limit: 限制返回结果的个数
            search_conditions: 分类后的搜索条件

        Returns:
            SearchResult: Domain层搜索结果
        """
        hits = response["hits"]["hits"]

        # 获取总数
        total_count: int = 0
        if isinstance(response["hits"]["total"], dict):
            total_count = response["hits"]["total"]["value"]

        # 判断是否为混合搜索
        is_hybrid_search = bool(
            search_conditions["vector"] and search_conditions["match"]
        )

        # 根据搜索类型处理结果
        if is_hybrid_search:
            documents = self._process_hybrid_search_results(
                cast("str", search_conditions["vector"][0].value), hits, limit
            )
        else:
            documents = self._process_structured_search_results(hits)

        return SearchResult(
            documents=documents,
            total_count=total_count,
            search_time_ms=search_time_ms,
        )

    def _process_hybrid_search_results(
        self,
        text_query: str,
        hits: list[dict[str, Any]],
        limit: int,
    ) -> list[DocumentResult]:
        """
        处理混合搜索结果：去重 + 重排序

        Args:
            hits: ES查询命中结果

        Returns:
            处理后的文档结果列表
        """

        chunks = [
            DocumentResult(
                content=hit["_source"],
                score=hit["_score"] if hit["_score"] is not None else 0.0,
            )
            for hit in hits
        ]

        # 去重处理
        seen = set()
        unique_chunks = []

        for chunk in chunks:
            identifier = (
                chunk.content["content"],
                chunk.content["file_metadata_id"],
            )
            if identifier not in seen:
                seen.add(identifier)
                unique_chunks.append(chunk)

        # 重排
        return self._reranker.rerank(text_query, unique_chunks)[:limit]

    @staticmethod
    def _process_structured_search_results(
        hits: list[dict[str, Any]],
    ) -> list[DocumentResult]:
        """
        处理结构化搜索结果：直接转换

        Args:
            hits: ES查询命中结果

        Returns:
            文档结果列表
        """
        documents = []
        for hit in hits:
            documents.append(
                DocumentResult(
                    id=hit["_id"],  # 使用ES文档ID
                    content=hit["_source"],  # 完整文档内容
                    score=hit["_score"] if hit["_score"] is not None else 0.0,
                )
            )
        return documents

    def save_for_structured_search(
        self, index_name: str, doc_id: str, doc_dict: dict[str, Any]
    ) -> None:
        """
        保存文档到Elasticsearch索引，如果文档已存在则整体覆盖

        Args:
            index_name: ES索引名称
            doc_id: 文档ID
            doc_dict: 文档内容字典

        Raises:
            RuntimeError: 文档存储失败时抛出
        """
        try:
            # 插入或完整覆盖
            response = self._client.index(
                index=index_name,
                id=doc_id,
                document=doc_dict,
                refresh="wait_for",
            )
            # 记录操作结果
            operation = (
                "创建" if response.get("result") == "created" else "覆盖"
            )
            logger.info(f"文档 {doc_id} 在索引 {index_name} 中{operation}成功")

        except Exception as e:
            error_msg = f"文档存储失败 - 索引: {index_name}, 文档ID: {doc_id}"
            logger.error(f"{error_msg}，错误: {e}")
            raise RuntimeError(f"{error_msg}: {str(e)}") from e
