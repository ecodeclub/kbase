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

import time
from collections.abc import Generator
from pprint import pprint
from typing import Any

import pytest
from elasticsearch import Elasticsearch
from fastapi.testclient import TestClient
from httpx import Response

from app.config.settings import settings


class TestVectorHybridSearch:
    """向量混合搜索测试

    包含：
    1. 向量混合搜索功能测试 (基于upload接口上传的数据)
    2. 混合搜索特有参数验证测试
    3. 错误处理和边界条件测试

    使用场景：
    - 通过upload接口上传的文档，使用search接口查询时，要用type=vector_hybrid
    """

    INDEX_PREFIX = "test_vector_hybrid_url"

    @pytest.fixture(scope="class", autouse=True)
    def setup_environment(
        self,
        client: TestClient,
        es_client: Elasticsearch,
    ) -> Generator[None, Any, None]:
        """准备测试环境（索引+数据）"""

        # 1. 清理已存在的索引
        self._cleanup_indexes(es_client, self.INDEX_PREFIX)

        # 2. 准备测试数据
        self._prepare_test_data(client, es_client, self.INDEX_PREFIX)

        # 3. 执行所有测试
        yield

        # 4. 清理测试索引
        self._cleanup_indexes(es_client, self.INDEX_PREFIX)

    def _cleanup_indexes(
        self, es_client: Elasticsearch, index_prefix: str
    ) -> None:
        """清理测试索引"""
        metadata_index = self._get_metadata_index_name(index_prefix)
        chunk_index = self._get_chunk_index_name(index_prefix)

        try:
            if es_client.indices.exists(index=metadata_index):
                es_client.indices.delete(index=metadata_index)
            if es_client.indices.exists(index=chunk_index):
                es_client.indices.delete(index=chunk_index)
        except Exception as e:
            print(f"⚠️ 清理索引时出错: {e}")

    @staticmethod
    def _get_metadata_index_name(index_prefix: str) -> str:
        """获取metadata索引名"""
        return index_prefix + settings.elasticsearch.metadata_index_suffix

    @staticmethod
    def _get_chunk_index_name(index_prefix: str) -> str:
        """获取chunk索引名"""
        return index_prefix + settings.elasticsearch.chunk_index_suffix

    def _prepare_test_data(
        self,
        client: TestClient,
        es_client: Elasticsearch,
        index_prefix: str,
    ) -> None:
        """准备向量混合搜索测试数据"""

        print("\n🚀 开始准备向量混合搜索测试环境")
        print(f"🔗 URL上传索引前缀: {self.INDEX_PREFIX}")

        # 通过URL上传准备数据
        self._upload_test_url(client)

        # 等待数据处理完成
        self._wait_for_test_data_ready(index_prefix, es_client)

        print("✅ 向量搜索测试数据准备完成")

    def _upload_test_url(self, client: TestClient) -> None:
        """通过URL上传准备测试数据"""
        bucket_name = settings.tencent_oss.bucket
        cos_url = f"https://{bucket_name}.cos.{settings.tencent_oss.region}.myqcloud.com/kbase-temp/02_test.pdf"

        response = client.post(
            "/api/v1/documents/upload-from-url",
            json={
                "url": cos_url,
                "index_prefix": self.INDEX_PREFIX,
            },
        )

        assert response.status_code == 200, f"URL上传失败: {response.json()}"
        task_id = response.json()["task_id"]
        print(f"🔗 URL上传任务创建成功: {task_id}")
        self._wait_for_task_completion(client, task_id)

    @staticmethod
    def _wait_for_task_completion(
        client: TestClient, task_id: str, max_wait: int = 30
    ) -> None:
        """等待后台任务完成"""
        for _ in range(max_wait):
            response = client.get(f"/api/v1/tasks/{task_id}")
            if response.status_code == 200:
                status = response.json()["status"]
                if status == "completed":
                    return
                elif status.startswith("failed"):
                    pytest.fail(f"任务处理失败: {status}")
            time.sleep(1)
        pytest.fail(f"任务处理超时: {task_id}")

    def _wait_for_test_data_ready(
        self, index_prefix: str, es_client: Elasticsearch
    ) -> None:
        """等待测试数据就绪"""
        print("⏳ 等待上传任务完成和数据索引...")

        max_wait_time = 30
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            # 检查URL上传索引
            url_metadata_count = self._get_index_doc_count(
                es_client, self._get_metadata_index_name(index_prefix)
            )
            url_chunk_count = self._get_index_doc_count(
                es_client, self._get_chunk_index_name(index_prefix)
            )

            print(
                f"📊 当前数据统计: URL上传(metadata: {url_metadata_count}, chunks: {url_chunk_count}) "
            )

            # 检查是否都有数据了
            if url_metadata_count > 0 and url_chunk_count > 0:
                print("✅ 所有上传任务完成")
                return

            time.sleep(2)

        # 超时但尽量继续测试
        print("⚠️ 等待上传超时，但继续进行测试")

    @staticmethod
    def _get_index_doc_count(es_client: Elasticsearch, index_name: str) -> int:
        """获取索引中的文档数量"""
        if not es_client.indices.exists(index=index_name):
            return 0

        # 刷新索引确保数据可见
        es_client.indices.refresh(index=index_name)

        try:
            response = es_client.count(index=index_name)
            return int(response["count"])
        except Exception as e:
            print(f"获取索引中文档总数失败：{e}")
            return 0

    # ===== 向量混合搜索功能测试 =====

    def test_hybrid_search(self, client: TestClient) -> None:
        """测试基础向量混合搜索 - 基于URL上传的数据"""
        value = "统计型数据"
        response = client.post(
            "/api/v1/search",
            json={
                "type": "vector_hybrid",
                "query": {
                    "index": self._get_chunk_index_name(self.INDEX_PREFIX),
                    "conditions": [
                        {
                            "field": "content",
                            "op": "match",
                            "value": value,
                        }
                    ],
                },
                "top_k": 3,
            },
        )
        pprint(f"查询字段：{value}")
        self._assert_response(response)

    @staticmethod
    def _assert_response(response: Response) -> None:
        assert response.status_code == 200
        data = response.json()

        # 验证响应结构
        assert isinstance(data["results"], list)

        # 验证结果格式
        for result in data["results"]:
            assert "text" in result  # VectorHybridSearchResult格式
            assert "file_metadata_id" in result
            assert "score" in result
            assert isinstance(result["score"], int | float)
            # 不应该包含StructuredSearchResult的字段
            assert "id" not in result
            assert "document" not in result
            pprint(result)

    def test_semantic_similarity(self, client: TestClient) -> None:
        """测试语义相似性搜索"""
        value = "用户中心并发过高"
        response = client.post(
            "/api/v1/search",
            json={
                "type": "vector_hybrid",
                "query": {
                    "index": self._get_chunk_index_name(self.INDEX_PREFIX),
                    "conditions": [
                        {
                            "field": "content",
                            "op": "match",
                            "value": value,
                        }
                    ],
                },
                "top_k": 2,
            },
        )
        pprint(f"查询字段：{value}")
        self._assert_response(response)

    # ===== 参数验证测试 =====

    def test_invalid_multiple_conditions(self, client: TestClient) -> None:
        """测试向量混合搜索不允许多个条件"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "vector_hybrid",
                "query": {
                    "index": self._get_chunk_index_name(self.INDEX_PREFIX),
                    "conditions": [
                        {"field": "content", "op": "match", "value": "Python"},
                        {
                            "field": "content",
                            "op": "match",
                            "value": "机器学习",
                        },
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 422  # Validation error

    def test_invalid_term_condition(self, client: TestClient) -> None:
        """测试向量混合搜索不允许term操作符"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "vector_hybrid",
                "query": {
                    "index": self._get_chunk_index_name(self.INDEX_PREFIX),
                    "conditions": [
                        {"field": "content", "op": "term", "value": "Python"}
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 422  # Validation error

    def test_empty_condition_value(self, client: TestClient) -> None:
        """测试空查询处理"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "vector_hybrid",
                "query": {
                    "index": self._get_chunk_index_name(self.INDEX_PREFIX),
                    "conditions": [
                        {"field": "content", "op": "match", "value": ""}
                    ],
                },
                "top_k": 5,
            },
        )

        # 空查询应该返回 422 验证错误
        assert response.status_code == 422

    def test_nonexistent_index(self, client: TestClient) -> None:
        """测试不存在的索引"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "vector_hybrid",
                "query": {
                    "index": "不存在的索引_chunks",
                    "conditions": [
                        {"field": "content", "op": "match", "value": "测试"}
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 404

    def test_search_with_filters(
        self, es_client: Elasticsearch, client: TestClient
    ) -> None:
        """测试带过滤条件的向量混合搜索"""
        value = "缓存"
        chunk_index_number = self._get_index_doc_count(
            es_client, self._get_chunk_index_name(self.INDEX_PREFIX)
        )
        response = client.post(
            "/api/v1/search",
            json={
                "type": "vector_hybrid",
                "query": {
                    "index": self._get_chunk_index_name(self.INDEX_PREFIX),
                    "conditions": [
                        {"field": "content", "op": "match", "value": value}
                    ],
                    "filters": {
                        "range": {
                            "chunk_index": {"gte": chunk_index_number - 1}
                        }
                    },  # 包含所有chunk
                },
                "top_k": 5,
            },
        )

        pprint(f"查询字段：{value}")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["results"], list)
        assert len(data["results"]) == 1
        pprint(f"{data['results']}")

    def test_top_k_limit(self, client: TestClient) -> None:
        """测试top_k参数限制"""
        for top_k in [1, 2, 3]:
            response = client.post(
                "/api/v1/search",
                json={
                    "type": "vector_hybrid",
                    "query": {
                        "index": self._get_chunk_index_name(self.INDEX_PREFIX),
                        "conditions": [
                            {"field": "content", "op": "match", "value": "中心"}
                        ],
                    },
                    "top_k": top_k,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data["results"], list)
            assert len(data["results"]) <= top_k
            print(
                f"📊 Top-K={top_k} 限制测试通过: 返回 {len(data['results'])} 个结果"
            )

    def test_score_ordering(self, client: TestClient) -> None:
        """测试结果按分数排序"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "vector_hybrid",
                "query": {
                    "index": self._get_chunk_index_name(self.INDEX_PREFIX),
                    "conditions": [
                        {"field": "content", "op": "match", "value": "缓存"}
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证分数降序排列
        scores = [result["score"] for result in data["results"]]
        assert scores == sorted(scores, reverse=True), "结果应该按分数降序排列"
        print(f"📊 分数排序验证通过: {scores}")
