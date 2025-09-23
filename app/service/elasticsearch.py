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
from datetime import UTC, datetime
from typing import Any, Protocol

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from langchain_core.documents import Document as LangChainDocument

from app.config.settings import Settings
from app.domain.document import Document
from app.domain.search import ContextChunk, SearchRequest, SearchResponse

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
        self, query: str, results: list[ContextChunk]
    ) -> list[ContextChunk]: ...


class ElasticsearchService:
    def __init__(
        self,
        client: Elasticsearch,
        loader: Loader,
        splitter: Splitter,
        embedder: Embedder,
        reranker: Reranker,
        metadata_index: str,
        chunk_index: str,
        settings: Settings,
    ) -> None:
        self.client = client
        self.loader = loader
        self.splitter = splitter
        self.embedder = embedder
        self.reranker = reranker
        self.metadata_index = metadata_index
        self.chunk_index = chunk_index
        self.settings = settings
        self._ensure_metadata_index_exists()
        self._ensure_chunk_index_exists()

    def _ensure_metadata_index_exists(self) -> None:
        """确保索引 metadata_index 存在"""
        if not self.client.indices.exists(index=self.metadata_index):
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
                self.client.indices.create(index=self.metadata_index, body=body)
            except Exception as e:
                raise e

    def _ensure_chunk_index_exists(self) -> None:
        """确保索引chunk_index存在"""
        if not self.client.indices.exists(index=self.chunk_index):
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
                            "dims": self.embedder.dimensions,
                            "similarity": self.embedder.similarity_metric,
                            "index": True,
                            "index_options": {
                                "type": self.settings.embedder.index_type,
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
                self.client.indices.create(index=self.chunk_index, body=body)
            except Exception as e:
                raise e

    def store(self, document: Document) -> str:
        """
        将文档存入双索引系统。
        1. 存储文件元数据到 file_metadatas。
        2. 切分文件为chunks，并将 chunks相关信息 及对应的源文件的 file_metadata_id 存入 file_chunks。
        :return: 在 file_metadatas 中生成的文档 ID。
        """
        metadata_id = self._create_metadata(document)
        document.id = metadata_id  # 确保 document 对象持有 ID
        logger.info(f"元数据占位符创建成功，ID: {metadata_id}")

        try:
            # 尝试创建和存储 chunks。失败会抛出异常。
            created_chunks_count = self._create_chunks(document)
            logger.info(f"成功存储 {created_chunks_count} 个文档块。")

            # Chunks 存储成功后，才更新元数据中的 total_chunks
            now_millis = int(datetime.now(UTC).timestamp() * 1000)
            self.client.update(
                index=self.metadata_index,
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
            self.client.indices.refresh(index=self.chunk_index)
            return metadata_id

        except Exception as e:
            # 如果上述 try 块中任何一步失败，执行回滚操作
            logger.error(f"文档处理失败，错误: {e}。正在回滚元数据...")
            self.client.delete(
                index=self.metadata_index, id=metadata_id, refresh=True
            )
            logger.info(f"元数据 {metadata_id} 已被成功删除。")
            # 重新抛出异常，让上层调用者知道操作失败
            raise RuntimeError("文档存储失败，已回滚。") from e

    def _create_metadata(self, document: Document) -> str:
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
        meta_response = self.client.index(
            index=self.metadata_index, document=doc, refresh="wait_for"
        )
        return str(meta_response["_id"])

    def _create_chunks(self, document: Document) -> int:
        """增强错误处理，支持部分回滚"""
        if not document.id:
            raise ValueError("文档ID未设置")

        chunks = self.splitter.split_documents(self.loader.load(document))
        if not chunks:
            raise RuntimeError("未提取出任何文本块")

        content_vectors = self.embedder.embed_documents(
            [chunk.page_content for chunk in chunks]
        )

        chunk_docs = []
        chunk_ids = []  # 记录已创建的chunk IDs

        try:
            for i, (chunk, content_vector) in enumerate(
                zip(chunks, content_vectors, strict=True)
            ):
                doc = {
                    "_index": self.chunk_index,
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
                client=self.client,
                actions=chunk_docs,
                stats_only=False,
                raise_on_error=False,
            )

            if failed:
                # 清理已成功写入的chunks
                self._cleanup_chunks(chunk_ids[:success])
                raise RuntimeError(f"批量写入失败: {failed}")

            return success

        except Exception:
            # 确保清理所有可能已写入的chunks
            if chunk_ids:
                self._cleanup_chunks(chunk_ids)
            raise

    def _cleanup_chunks(self, chunk_ids: list[str]) -> None:
        """清理指定的chunks"""
        for chunk_id in chunk_ids:
            try:
                self.client.delete(index=self.chunk_index, id=chunk_id)
            except Exception as e:
                logger.error(f"删除文档分失败，错误: {e}。")
                pass

    # 在 ElasticsearchService 中添加
    def delete_document(self, metadata_id: str) -> bool:
        """删除文档及其所有chunks"""
        try:
            # 先删除所有相关chunks
            self.client.delete_by_query(
                index=self.chunk_index,
                body={"query": {"term": {"file_metadata_id": metadata_id}}},
                refresh=True,
            )
            # 删除元数据
            self.client.delete(
                index=self.metadata_index, id=metadata_id, refresh=True
            )
            return True
        except Exception as e:
            logger.error(f"删除文档失败: {e}")
            return False

    def search(self, request: SearchRequest) -> SearchResponse:
        """在 file_chunks 索引中执行搜索。"""
        if not request.query:
            # 如果查询为空，可以考虑返回最近的文件等，这里暂时返回空
            return SearchResponse(context=[])

        standard_query, filter_clause = self._build_filtered_queries(
            request.query, request.filters
        )

        # 定义召回阶段要获取的文档数量，应大于最终的 top_k
        # 这是一个超参数，可以根据需求调整
        retrieval_size = request.top_k * self.settings.retrieval.multiplier
        query_vector = self.embedder.embed_documents([request.query])[0]

        # 使用实用的混合搜索语法：knn + query 组合（兼容 ES 9.x）
        vector_weight = self.settings.retrieval.vector_weight
        text_weight = self.settings.retrieval.text_weight

        # 构建搜索体
        search_body: dict[str, Any] = {
            "size": retrieval_size,
            "_source": ["content", "file_metadata_id"],
            "knn": {
                "field": "content_vector",
                "query_vector": query_vector,
                "k": retrieval_size,
                "num_candidates": 100,
                "boost": vector_weight,
            },
            "query": {
                "bool": {
                    "should": [
                        {
                            "match": {
                                "content": {
                                    "query": request.query,
                                    "boost": text_weight * 0.5,
                                }
                            }
                        },
                        {
                            "match_phrase": {
                                "content": {
                                    "query": request.query,
                                    "boost": text_weight * 0.3,
                                }
                            }
                        },
                    ],
                    "minimum_should_match": 0,
                }
            },
        }

        # 如果有过滤条件，添加到搜索体中
        if filter_clause:
            # 为 knn 添加过滤器
            search_body["knn"]["filter"] = filter_clause
            # 为 query 添加过滤器
            search_body["query"]["bool"]["filter"] = filter_clause

        # 执行混合搜索
        response = self.client.search(index=self.chunk_index, body=search_body)

        # 格式化召回结果
        retrieved_chunks = [
            ContextChunk(
                text=hit["_source"]["content"],
                file_metadata_id=hit["_source"]["file_metadata_id"],
                score=hit["_score"] if hit["_score"] is not None else 0.0,
            )
            for hit in response["hits"]["hits"]
        ]

        # 去重
        seen = set()
        unique_chunks = []
        for chunk in retrieved_chunks:
            identifier = (chunk.text, chunk.file_metadata_id)
            if identifier not in seen:
                seen.add(identifier)
                unique_chunks.append(chunk)

        # 重排
        reranked_chunks = self.reranker.rerank(request.query, unique_chunks)

        # 截取最终的 top_k
        final_context = reranked_chunks[: request.top_k]

        return SearchResponse(context=final_context)

    @staticmethod
    def _build_filtered_queries(
        query: str, filters: dict[str, Any] | None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """
        根据用户查询和过滤器，动态构建用于 standard 和 knn 检索器的查询。

        :param query: 用户的查询字符串。
        :param filters: 一个包含字段和期望值的字典，用于过滤。
        :return: 一个元组，包含:
                 - standard_query (dict): 用于 standard retriever 的完整查询体。
                 - knn_filter (list): 用于 knn retriever 的过滤器列表。
        """
        # 准备 standard retriever 的核心 query 部分 (match query)
        standard_query_part = {
            "match": {"content": {"query": query, "boost": 0.5}}
        }

        # 根据 filters 构建 filter_clause
        filter_clause: list[dict[str, Any]] = []
        if filters:
            for field, value in filters.items():
                if isinstance(value, list):
                    filter_clause.append({"terms": {field: value}})
                else:
                    filter_clause.append({"term": {field: value}})

        # 简单情况：如果没有过滤器，直接返回最简单的查询
        if not filter_clause:
            # 此处 standard_query_part 就是最终的查询
            return standard_query_part, filter_clause

        # 构建复杂的 bool 查询并返回
        standard_query = {
            "bool": {"must": [standard_query_part], "filter": filter_clause}
        }

        return standard_query, filter_clause
