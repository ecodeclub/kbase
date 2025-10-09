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

import json
from collections.abc import Generator
from typing import Any

import pytest
from elasticsearch import Elasticsearch
from fastapi.testclient import TestClient


class TestStructuredSearch:
    """结构化搜索测试

    包含：
    1. 结构化搜索功能测试
    2. 通用参数验证测试（复用测试环境，后续可能调整）
    """

    TEST_INDEX = "test_search_structured"

    @pytest.fixture(scope="class", autouse=True)
    def setup_environment(
        self, client: TestClient, es_client: Elasticsearch
    ) -> Generator[None, Any]:
        """准备测试环境（索引+数据）"""

        # 1. 清理已存在的索引
        if es_client.indices.exists(index=self.TEST_INDEX):
            es_client.indices.delete(index=self.TEST_INDEX)

        # 2. 创建结构化搜索测试索引
        es_client.indices.create(
            index=self.TEST_INDEX,
            body={
                "mappings": {
                    "properties": {
                        "role": {"type": "keyword"},  # 精确匹配
                        "level": {"type": "keyword"},  # 精确匹配
                        "content": {"type": "text"},  # 全文搜索
                        "department": {"type": "keyword"},  # 精确匹配
                        "status": {"type": "keyword"},  # 精确匹配
                        "tags": {"type": "keyword"},  # 精确匹配
                        "salary": {"type": "integer"},  # 数值类型
                    }
                }
            },
        )

        # 3. 准备测试数据
        self._prepare_test_data(client, es_client)

        # 4. 执行所有测试
        yield

        # 5. 清理测试索引
        if es_client.indices.exists(index=self.TEST_INDEX):
            es_client.indices.delete(index=self.TEST_INDEX)

    def _prepare_test_data(
        self, client: TestClient, es_client: Elasticsearch
    ) -> None:
        """准备结构化搜索测试数据（在fixture中调用，只执行一次）"""

        test_documents = [
            {
                "id": "backend_senior_1",
                "data": {
                    "role": "后端",
                    "level": "高级",
                    "content": "MySQL设计及性能优化是后端开发的重要技能，包括索引优化、查询优化等",
                    "department": "技术部",
                    "status": "active",
                    "tags": "database",
                    "salary": 25000,
                },
            },
            {
                "id": "backend_junior_1",
                "data": {
                    "role": "后端",
                    "level": "初级",
                    "content": "Python 基础语法学习，包括变量、函数、类等概念",
                    "department": "技术部",
                    "status": "active",
                    "tags": "programming",
                    "salary": 15000,
                },
            },
            {
                "id": "frontend_senior_1",
                "data": {
                    "role": "前端",
                    "level": "高级",
                    "content": "React 组件设计模式，状态管理最佳实践",
                    "department": "技术部",
                    "status": "inactive",
                    "tags": "frontend",
                    "salary": 22000,
                },
            },
            {
                "id": "backend_senior_2",
                "data": {
                    "role": "后端",
                    "level": "高级",
                    "content": "分布式系统设计微服务架构实践指南",
                    "department": "技术部",
                    "status": "active",
                    "tags": "architecture",
                    "salary": 30000,
                },
            },
            {
                "id": "qa_middle_1",
                "data": {
                    "role": "测试",
                    "level": "中级",
                    "content": "自动化测试框架设计，性能测试和优化经验",
                    "department": "质量部",
                    "status": "active",
                    "tags": "testing",
                    "salary": 18000,
                },
            },
        ]

        # 使用save接口插入所有测试数据
        for doc in test_documents:
            response = client.post(
                "/api/v1/documents/save",
                json={
                    "index": self.TEST_INDEX,
                    "key": doc["id"],
                    "doc_json": json.dumps(doc["data"]),
                },
            )
            assert response.status_code == 200, (
                f"保存文档失败: {response.json()}"
            )

        # 刷新索引确保数据可搜索
        es_client.indices.refresh(index=self.TEST_INDEX)

    # ===== 结构化搜索功能测试 =====

    def test_single_exact_match(self, client: TestClient) -> None:
        """测试单个精确匹配 - 按角色搜索后端开发者"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "structured",
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [
                        {"field": "role", "op": "term", "value": "后端"}
                    ],
                },
                "top_k": 5,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证响应结构和数据
        assert len(data["results"]) == 3  # 3个后端开发者

        # 验证具体结果
        backend_ids = {
            "backend_senior_1",
            "backend_junior_1",
            "backend_senior_2",
        }
        actual_ids = {result["id"] for result in data["results"]}
        assert actual_ids == backend_ids

        # 验证结果格式
        for result in data["results"]:
            assert "id" in result
            assert "document" in result
            assert "score" in result
            assert result["document"]["role"] == "后端"

    def test_multiple_exact_match(self, client: TestClient) -> None:
        """测试多个精确匹配"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "structured",
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [
                        {"field": "role", "op": "term", "value": "后端"},
                        {"field": "level", "op": "term", "value": "高级"},
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["results"]) == 2  # 2个高级后端开发者

        # 验证具体结果
        expected_ids = {"backend_senior_1", "backend_senior_2"}
        actual_ids = {result["id"] for result in data["results"]}
        assert actual_ids == expected_ids

        for result in data["results"]:
            assert result["document"]["role"] == "后端"
            assert result["document"]["level"] == "高级"

    def test_single_full_text_match(self, client: TestClient) -> None:
        """测试单个全文搜索 - 内容匹配"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "structured",
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [
                        {
                            "field": "content",
                            "op": "match",
                            "value": "MySQL 性能优化",
                        }
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 2

        # 验证结果包含相关内容
        found_mysql_doc = False
        for result in data["results"]:
            if "MySQL" in result["document"]["content"]:
                found_mysql_doc = True
                break
        assert found_mysql_doc, "应该找到包含MySQL的文档"

    def test_multiple_full_text_match(self, client: TestClient) -> None:
        """测试多个全文搜索"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "structured",
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [
                        {"field": "content", "op": "match", "value": "系统"},
                        {"field": "content", "op": "match", "value": "模式"},
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["results"]) == 1

        # 验证AND关系：必须同时包含两个关键词
        for result in data["results"]:
            content = result["document"]["content"]
            assert ("系" in content or "统" in content) and (
                "模" in content or "式" in content
            ), f"文档内容应同时包含'系''统''模''式': {content}"

    def test_mixed_exact_and_full_text_match(self, client: TestClient) -> None:
        """测试混合搜索 - 精确匹配+全文搜索"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "structured",
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [
                        {"field": "role", "op": "term", "value": "后端"},
                        {"field": "status", "op": "term", "value": "active"},
                        {"field": "content", "op": "match", "value": "设计"},
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 2

        for result in data["results"]:
            doc = result["document"]
            assert doc["role"] == "后端"
            assert doc["status"] == "active"
            assert "设计" in doc["content"]

    def test_complex_mixed_conditions(self, client: TestClient) -> None:
        """测试复杂混合条件 - 部门+级别+内容"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "structured",
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [
                        {
                            "field": "department",
                            "op": "term",
                            "value": "技术部",
                        },  # 精确匹配
                        {
                            "field": "level",
                            "op": "term",
                            "value": "高级",
                        },  # 精确匹配
                        {
                            "field": "content",
                            "op": "match",
                            "value": "设计",
                        },  # 全文匹配
                    ],
                },
                "top_k": 5,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["results"]) == 3

        for result in data["results"]:
            doc = result["document"]
            assert doc["department"] == "技术部"
            assert doc["level"] == "高级"
            assert "设计" in doc["content"]

    def test_with_range_filters(self, client: TestClient) -> None:
        """测试范围过滤 - 薪资范围"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "structured",
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [
                        {"field": "role", "op": "term", "value": "后端"}
                    ],
                    "filters": {
                        "range": {
                            "salary": {"gte": 20000}
                        }  # 薪资>=20000的过滤条件
                    },
                },
                "top_k": 5,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["results"]) == 2

        # 验证具体地期望结果
        expected_ids = {"backend_senior_1", "backend_senior_2"}
        actual_ids = {result["id"] for result in data["results"]}
        assert actual_ids == expected_ids, (
            f"期望 {expected_ids}，实际 {actual_ids}"
        )

        # 验证过滤条件生效
        for result in data["results"]:
            assert result["document"]["role"] == "后端"
            assert result["document"]["salary"] >= 20000

    def test_top_k_limit(self, client: TestClient) -> None:
        """测试结果数量限制"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "structured",
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [
                        {"field": "role", "op": "term", "value": "后端"}
                    ],
                },
                "top_k": 2,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["results"]) <= 2  # 最多返回2个结果
        assert (
            len(data["results"]) == 2
        )  # 应该正好有2个结果（因为有3个后端，限制为2）

        # 验证返回的都是后端
        for result in data["results"]:
            assert result["document"]["role"] == "后端"

    def test_no_results_found(self, client: TestClient) -> None:
        """测试无匹配结果"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "structured",
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [
                        {"field": "role", "op": "term", "value": "不存在的角色"}
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["results"]) == 0

    # ===== 参数验证测试 =====
    # 注：这些测试复用结构化搜索的测试环境
    # 如果向量混合搜索需要不同的校验规则，在vector_hybrid_search_test.py中单独添加

    def test_invalid_type(self, client: TestClient) -> None:
        """测试无效搜索类型"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "invalid_type",
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [
                        {"field": "role", "op": "term", "value": "后端"}
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 422

    def test_invalid_operator(self, client: TestClient) -> None:
        """测试无效操作符"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "structured",
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [
                        {"field": "role", "op": "invalid_op", "value": "后端"}
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 422

    def test_missing_field_value(self, client: TestClient) -> None:
        """测试缺少必需字段"""
        response = client.post(
            "/api/v1/search",
            json={
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [
                        {"field": "role", "op": "term", "value": ""}
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 422

    def test_empty_conditions(self, client: TestClient) -> None:
        """测试空条件列表"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "structured",
                "query": {
                    "index": self.TEST_INDEX,
                    "conditions": [],
                },
                "top_k": 3,
            },
        )

        assert response.status_code == 422

    def test_nonexistent_index(self, client: TestClient) -> None:
        """测试不存在的索引"""
        response = client.post(
            "/api/v1/search",
            json={
                "type": "structured",
                "query": {
                    "index": "不存在的索引",
                    "conditions": [
                        {"field": "role", "op": "term", "value": "后端"}
                    ],
                },
                "top_k": 3,
            },
        )

        assert response.status_code >= 400
