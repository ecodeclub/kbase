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

import json
from collections.abc import Generator
from typing import Any, cast

import pytest
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError, TransportError
from fastapi.testclient import TestClient


class TestSaveEndpoint:
    """测试文档保存接口"""

    TEST_INDEX = "test_save_index"

    @pytest.fixture(scope="class", autouse=True)
    def setup_test_index(
        self, es_client: Elasticsearch
    ) -> Generator[None, Any]:
        """设置测试索引"""
        # 如果索引存在则删除（清理之前的测试）
        if es_client.indices.exists(index=self.TEST_INDEX):
            es_client.indices.delete(index=self.TEST_INDEX)

        # 创建测试索引
        es_client.indices.create(
            index=self.TEST_INDEX,
            body={
                "mappings": {
                    "properties": {
                        "role": {
                            "type": "keyword"
                        },  # 精确匹配：后端、前端、测试等
                        "level": {
                            "type": "keyword"
                        },  # 精确匹配：初级、中级、高级等
                        "content": {"type": "text"},  # 模糊匹配：详细描述内容
                    }
                }
            },
        )

        yield

        # 清理：删除测试索引
        if es_client.indices.exists(index=self.TEST_INDEX):
            es_client.indices.delete(index=self.TEST_INDEX)

    def _get_document_from_es(
        self, es_client: Elasticsearch, doc_id: str
    ) -> dict[str, Any] | None:
        """从ES获取文档"""
        try:
            response = es_client.get(index=self.TEST_INDEX, id=doc_id)
            return cast("dict[str, Any]", response["_source"])
        except NotFoundError:
            return None
        except TransportError as e:
            print(
                f"ES获取文档失败 - 索引: {self.TEST_INDEX}, 文档ID: {doc_id}, 错误: {e}"
            )
            raise

    def _document_exists_in_es(
        self, es_client: Elasticsearch, doc_id: str
    ) -> bool:
        """检查文档是否存在于ES中"""
        try:
            es_client.get(index=self.TEST_INDEX, id=doc_id)
            return True
        except NotFoundError:
            return False
        except TransportError as e:
            print(
                f"ES检查文档存在性失败 - 索引: {self.TEST_INDEX}, 文档ID: {doc_id}, 错误: {e}"
            )
            raise

    def test_save_new_document(
        self, client: TestClient, es_client: Elasticsearch
    ) -> None:
        """测试保存新文档"""

        doc_id = "backend_dev_1"
        doc_data = {
            "role": "后端",
            "level": "高级",
            "content": "负责用户管理系统的设计和开发，熟练掌握Python、Django等技术栈，具备丰富的微服务架构经验",
        }

        # 验证文档不存在
        assert not self._document_exists_in_es(es_client, doc_id), (
            "文档不应该预先存在"
        )

        # 调用保存接口并验证响应
        response = client.post(
            "/api/v1/documents/save",
            json={
                "index": self.TEST_INDEX,
                "key": doc_id,
                "doc_json": json.dumps(doc_data),
            },
        )
        assert response.status_code == 200
        response_data = response.json()
        assert "ok" in response_data["message"]

        # 验证文档已插入ES
        assert self._document_exists_in_es(es_client, doc_id), (
            "文档应该已经插入"
        )
        saved_doc = self._get_document_from_es(es_client, doc_id)
        assert saved_doc == doc_data

    def test_save_update_existing_document(
        self, client: TestClient, es_client: Elasticsearch
    ) -> None:
        """测试覆盖已存在的文档"""

        doc_id = "frontend_dev_1"
        original_doc = {
            "role": "前端",
            "level": "中级",
            "content": "负责企业级Web应用的前端开发，熟悉React和Vue框架",
        }
        updated_doc = {
            "role": "架构师",
            "level": "高级",
            "content": "负责企业级Web应用和移动端H5的前端开发，精通React、Vue、TypeScript，具备跨平台开发经验",
        }

        # 验证文档不存在
        assert not self._document_exists_in_es(es_client, doc_id), (
            "文档不应该预先存在"
        )

        # 先插入一个文档并验证原文档存在
        es_client.index(
            index=self.TEST_INDEX,
            id=doc_id,
            document=original_doc,
            refresh="wait_for",
        )
        assert self._document_exists_in_es(es_client, doc_id), "原文档应该存在"
        original_saved = self._get_document_from_es(es_client, doc_id)
        assert original_saved == original_doc

        # 调用保存接口进行覆盖
        response = client.post(
            "/api/v1/documents/save",
            json={
                "index": self.TEST_INDEX,
                "key": doc_id,
                "doc_json": json.dumps(updated_doc),
            },
        )

        # 验证响应
        assert response.status_code == 200
        response_data = response.json()
        assert "ok" in response_data["message"]

        # 验证文档已完全覆盖
        updated_saved = self._get_document_from_es(es_client, doc_id)
        assert updated_saved == updated_doc

    def test_save_invalid_json_format(self, client: TestClient) -> None:
        """测试无效的JSON格式"""

        response = client.post(
            "/api/v1/documents/save",
            json={
                "index": self.TEST_INDEX,
                "key": "test_invalid",
                "doc_json": '{"role": "后端", "level": "高级"',  # 无效JSON，缺少闭合括号
            },
        )

        assert response.status_code == 422  # Pydantic验证错误
        error_data = response.json()
        assert "detail" in error_data

    def test_save_empty_fields(self, client: TestClient) -> None:
        """测试空字段"""

        test_cases = [
            {
                "index": "",
                "key": "test",
                "doc_json": '{"role": "后端", "level": "高级", "content": "测试内容"}',
            },  # 空索引
            {
                "index": self.TEST_INDEX,
                "key": "",
                "doc_json": '{"role": "后端", "level": "高级", "content": "测试内容"}',
            },  # 空key
        ]

        for case in test_cases:
            response = client.post("/api/v1/documents/save", json=case)
            assert response.status_code == 422  # 字段验证错误
            error_data = response.json()
            assert "detail" in error_data

    def test_save_missing_fields(self, client: TestClient) -> None:
        """测试缺失字段"""

        test_cases = [
            {
                "key": "test",
                "doc_json": '{"role": "后端", "level": "高级", "content": "测试内容"}',
            },  # 缺失index
            {
                "index": self.TEST_INDEX,
                "doc_json": '{"role": "后端", "level": "高级", "content": "测试内容"}',
            },  # 缺失key
            {"index": self.TEST_INDEX, "key": "test"},  # 缺失doc_json
        ]

        for case in test_cases:
            response = client.post("/api/v1/documents/save", json=case)
            assert response.status_code == 422  # 缺失字段错误
            error_data = response.json()
            assert "detail" in error_data

    def test_save_invalid_index_name(self, client: TestClient) -> None:
        """测试无效索引名（模拟ES错误）"""

        response = client.post(
            "/api/v1/documents/save",
            json={
                "index": "INVALID_INDEX_NAME_WITH_UPPERCASE",  # ES不允许大写索引名
                "key": "test",
                "doc_json": '{"role": "后端", "level": "高级", "content": "测试ES错误处理"}',
            },
        )

        # 这应该触发service层的异常，返回500错误
        assert response.status_code == 500
        error_data = response.json()
        assert "文档存储失败" in error_data["detail"]
