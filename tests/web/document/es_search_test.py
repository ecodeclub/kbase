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


from collections.abc import Generator
from typing import Any

import pytest
from elasticsearch import Elasticsearch
from fastapi.testclient import TestClient


class TestESSearch:
    """ES代理转发API测试

    测试 /api/v1/es_search 接口的功能：
    1. 原样转发ES查询并返回ES原始响应
    2. 支持各种ES查询语法
    3. 错误处理
    """

    TEST_INDEX = "test_es_search_proxy"

    @pytest.fixture(scope="class", autouse=True)
    def setup_environment(
        self, client: TestClient, es_client: Elasticsearch
    ) -> Generator[None, Any]:
        """准备测试环境（索引+数据）"""

        # 1. 清理已存在的索引
        if es_client.indices.exists(index=self.TEST_INDEX):
            es_client.indices.delete(index=self.TEST_INDEX)

        # 2. 创建测试索引
        es_client.indices.create(
            index=self.TEST_INDEX,
            body={
                "mappings": {
                    "properties": {
                        "role": {"type": "keyword"},
                        "level": {"type": "keyword"},
                        "content": {"type": "text"},
                        "department": {"type": "keyword"},
                        "status": {"type": "keyword"},
                        "salary": {"type": "integer"},
                        "age": {"type": "integer"},
                    }
                }
            },
        )

        # 3. 准备测试数据
        self._prepare_test_data(es_client)

        # 4. 执行所有测试
        yield

        # 5. 清理测试索引
        if es_client.indices.exists(index=self.TEST_INDEX):
            es_client.indices.delete(index=self.TEST_INDEX)

    def _prepare_test_data(self, es_client: Elasticsearch) -> None:
        """准备测试数据"""
        test_documents = [
            {
                "role": "后端",
                "level": "高级",
                "content": "MySQL数据库设计及性能优化",
                "department": "技术部",
                "status": "active",
                "salary": 25000,
                "age": 30,
            },
            {
                "role": "后端",
                "level": "初级",
                "content": "Python基础语法学习",
                "department": "技术部",
                "status": "active",
                "salary": 15000,
                "age": 24,
            },
            {
                "role": "前端",
                "level": "高级",
                "content": "React组件设计模式",
                "department": "技术部",
                "status": "inactive",
                "salary": 22000,
                "age": 28,
            },
            {
                "role": "后端",
                "level": "高级",
                "content": "分布式系统架构设计",
                "department": "技术部",
                "status": "active",
                "salary": 30000,
                "age": 32,
            },
            {
                "role": "测试",
                "level": "中级",
                "content": "自动化测试框架",
                "department": "质量部",
                "status": "active",
                "salary": 18000,
                "age": 26,
            },
        ]

        # 批量插入
        for i, doc in enumerate(test_documents):
            es_client.index(index=self.TEST_INDEX, id=f"doc_{i + 1}", body=doc)

        # 刷新索引确保数据可搜索
        es_client.indices.refresh(index=self.TEST_INDEX)

    # ===== 基础查询测试 =====

    def test_match_all_query(self, client: TestClient) -> None:
        """测试 match_all 查询 - 返回所有文档"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "query": {"match_all": {}}
                },  # 注意：query 字段包含完整的ES查询体
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证ES原始响应结构
        assert "took" in data
        assert "hits" in data
        assert "total" in data["hits"]
        assert "hits" in data["hits"]

        # 验证返回所有文档
        assert data["hits"]["total"]["value"] == 5

    def test_term_query(self, client: TestClient) -> None:
        """测试 term 精确匹配查询"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {"query": {"term": {"role": "后端"}}},
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证结果
        assert data["hits"]["total"]["value"] == 3

        # 验证所有结果都是后端
        for hit in data["hits"]["hits"]:
            assert hit["_source"]["role"] == "后端"

    def test_match_query(self, client: TestClient) -> None:
        """测试 match 全文搜索"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {"query": {"match": {"content": "设计"}}},
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证有结果返回
        assert data["hits"]["total"]["value"] > 0

        # 验证返回的文档内容包含"设计"
        for hit in data["hits"]["hits"]:
            assert "设计" in hit["_source"]["content"]

    def test_bool_must_query(self, client: TestClient) -> None:
        """测试 bool must 组合查询（AND逻辑）"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"role": "后端"}},
                                {"term": {"level": "高级"}},
                            ]
                        }
                    }
                },
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证结果数量
        assert data["hits"]["total"]["value"] == 2

        # 验证所有结果都满足条件
        for hit in data["hits"]["hits"]:
            assert hit["_source"]["role"] == "后端"
            assert hit["_source"]["level"] == "高级"

    def test_bool_should_query(self, client: TestClient) -> None:
        """测试 bool should 组合查询（OR逻辑）"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "query": {
                        "bool": {
                            "should": [
                                {"term": {"role": "前端"}},
                                {"term": {"role": "测试"}},
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                },
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证结果数量
        assert data["hits"]["total"]["value"] == 2

        # 验证所有结果都是前端或测试
        for hit in data["hits"]["hits"]:
            assert hit["_source"]["role"] in ["前端", "测试"]

    def test_bool_filter_query(self, client: TestClient) -> None:
        """测试 bool filter 查询（不影响评分）"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "query": {
                        "bool": {
                            "must": [{"match": {"content": "设计"}}],
                            "filter": [{"term": {"status": "active"}}],
                        }
                    }
                },
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证所有结果都满足filter条件
        for hit in data["hits"]["hits"]:
            assert hit["_source"]["status"] == "active"
            assert "设计" in hit["_source"]["content"]

    def test_range_query(self, client: TestClient) -> None:
        """测试 range 范围查询"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "query": {"range": {"salary": {"gte": 20000, "lte": 30000}}}
                },
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证所有结果的薪资都在范围内
        assert data["hits"]["total"]["value"] == 3
        for hit in data["hits"]["hits"]:
            salary = hit["_source"]["salary"]
            assert 20000 <= salary <= 30000

    # ===== 高级功能测试 =====

    def test_query_with_size(self, client: TestClient) -> None:
        """测试带 size 参数的查询（限制返回数量）"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "query": {"match_all": {}},
                    "size": 2,  # size 参数放在 query 字段内
                },
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证返回的文档数量
        assert len(data["hits"]["hits"]) == 2

    def test_query_with_sort(self, client: TestClient) -> None:
        """测试带排序的查询"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "query": {"match_all": {}},
                    "sort": [{"salary": {"order": "desc"}}],
                    "size": 3,
                },
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证结果按薪资降序排列
        salaries = [hit["_source"]["salary"] for hit in data["hits"]["hits"]]
        assert salaries == sorted(salaries, reverse=True)

    def test_query_with_source_filtering(self, client: TestClient) -> None:
        """测试字段过滤（只返回指定字段）"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "query": {"match_all": {}},
                    "_source": ["role", "level"],
                    "size": 1,
                },
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证只返回指定字段
        hit = data["hits"]["hits"][0]
        source = hit["_source"]
        assert "role" in source
        assert "level" in source
        assert "content" not in source
        assert "salary" not in source

    def test_aggregation_query(self, client: TestClient) -> None:
        """测试聚合查询"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "size": 0,  # 不返回文档，只返回聚合结果
                    "aggs": {
                        "roles": {"terms": {"field": "role"}},
                        "avg_salary": {"avg": {"field": "salary"}},
                    },
                },
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证聚合结果存在
        assert "aggregations" in data
        assert "roles" in data["aggregations"]
        assert "avg_salary" in data["aggregations"]

        # 验证角色分组
        roles_buckets = data["aggregations"]["roles"]["buckets"]
        role_counts = {
            bucket["key"]: bucket["doc_count"] for bucket in roles_buckets
        }
        assert role_counts["后端"] == 3

        # 验证平均薪资
        avg_salary = data["aggregations"]["avg_salary"]["value"]
        assert avg_salary > 0

    def test_complex_nested_query(self, client: TestClient) -> None:
        """测试复杂嵌套查询"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"department": "技术部"}},
                                {
                                    "bool": {
                                        "should": [
                                            {"term": {"level": "高级"}},
                                            {"term": {"level": "中级"}},
                                        ]
                                    }
                                },
                            ],
                            "filter": [
                                {"range": {"age": {"gte": 25, "lte": 35}}}
                            ],
                        }
                    }
                },
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证所有结果都满足复杂条件
        for hit in data["hits"]["hits"]:
            source = hit["_source"]
            assert source["department"] == "技术部"
            assert source["level"] in ["高级", "中级"]
            assert 25 <= source["age"] <= 35

    # ===== 错误处理测试 =====

    def test_nonexistent_index(self, client: TestClient) -> None:
        """测试不存在的索引"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": "nonexistent_index_12345",
                "query": {"query": {"match_all": {}}},
            },
        )

        # FastAPI 应该返回错误（可能是404或500，取决于异常处理）
        assert response.status_code >= 400

    def test_invalid_query_syntax(self, client: TestClient) -> None:
        """测试无效的查询语法"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "query": {
                        "invalid_query_type": {
                            "field": "value"
                        }  # 不存在的查询类型
                    }
                },
            },
        )

        # FastAPI 应该返回错误
        assert response.status_code >= 400

    def test_empty_query(self, client: TestClient) -> None:
        """测试空查询对象"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {},  # 空查询
            },
        )

        assert response.status_code == 200
        data = response.json()

        # ES会将空查询视为match_all
        assert data["hits"]["total"]["value"] == 5

    def test_missing_required_fields(self, client: TestClient) -> None:
        """测试缺少必需字段"""
        # 缺少 query 字段
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
            },
        )

        assert response.status_code == 422

        # 缺少 index 字段
        response = client.post(
            "/api/v1/es_search",
            json={
                "query": {"query": {"match_all": {}}},
            },
        )

        assert response.status_code == 422

    def test_empty_index_name(self, client: TestClient) -> None:
        """测试空索引名称"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": "",  # 空字符串
                "query": {"query": {"match_all": {}}},
            },
        )

        assert response.status_code == 422  # Pydantic validation 会拦截

    # ===== 边界测试 =====

    def test_very_large_size(self, client: TestClient) -> None:
        """测试非常大的 size 参数"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {"query": {"match_all": {}}, "size": 10000},
            },
        )

        # ES 可能会返回错误或限制结果数量
        # 这取决于ES的配置（默认max_result_window是10000）
        assert response.status_code in [200, 400, 500]

    def test_query_with_from_pagination(self, client: TestClient) -> None:
        """测试分页查询"""
        # 第一页
        response1 = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "query": {"match_all": {}},
                    "from": 0,
                    "size": 2,
                    "sort": [{"salary": {"order": "asc"}}],
                },
            },
        )

        # 第二页
        response2 = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {
                    "query": {"match_all": {}},
                    "from": 2,
                    "size": 2,
                    "sort": [{"salary": {"order": "asc"}}],
                },
            },
        )

        assert response1.status_code == 200
        assert response2.status_code == 200

        data1 = response1.json()
        data2 = response2.json()

        # 验证分页结果不重复
        ids1 = {hit["_id"] for hit in data1["hits"]["hits"]}
        ids2 = {hit["_id"] for hit in data2["hits"]["hits"]}
        assert len(ids1 & ids2) == 0  # 交集为空

    def test_response_structure_completeness(self, client: TestClient) -> None:
        """测试响应结构完整性 - 验证ES原始响应的关键字段都存在"""
        response = client.post(
            "/api/v1/es_search",
            json={
                "index": self.TEST_INDEX,
                "query": {"query": {"match_all": {}}, "size": 1},
            },
        )

        assert response.status_code == 200
        data = response.json()

        # 验证ES响应的关键结构
        assert "took" in data  # 查询耗时
        assert "timed_out" in data  # 是否超时
        assert "_shards" in data  # 分片信息
        assert "hits" in data  # 命中结果

        # 验证hits结构
        assert "total" in data["hits"]
        assert "value" in data["hits"]["total"]
        assert "relation" in data["hits"]["total"]
        assert "max_score" in data["hits"]
        assert "hits" in data["hits"]

        # 验证单个hit的结构
        if len(data["hits"]["hits"]) > 0:
            hit = data["hits"]["hits"][0]
            assert "_index" in hit
            assert "_id" in hit
            assert "_score" in hit
            assert "_source" in hit
