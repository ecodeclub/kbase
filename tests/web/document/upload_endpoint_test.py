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

import time
from collections.abc import Callable
from pathlib import Path

import pytest
from elasticsearch import Elasticsearch
from fastapi.testclient import TestClient

from app.config.settings import settings


class TestUploadEndpoint:
    """
    上传接口端到端测试类，测试路径为 /api/v1/documents/。
    使用不同的index_prefix实现数据隔离，用ES Client直接验证ES存储结果。
    """

    # 数据隔离：两个接口使用不同的索引前缀
    FILE_UPLOAD_INDEX_PREFIX = "test_file_upload"
    URL_UPLOAD_INDEX_PREFIX = "test_url_upload"

    @staticmethod
    def _get_metadata_index_name(index_prefix: str) -> str:
        """获取metadata索引名"""
        return index_prefix + settings.elasticsearch.metadata_index_suffix

    @staticmethod
    def _get_chunk_index_name(index_prefix: str) -> str:
        """获取chunk索引名"""
        return index_prefix + settings.elasticsearch.chunk_index_suffix

    def _verify_es_data_exists(
        self,
        es_client: Elasticsearch,
        index_prefix: str,
        expected_filename: str,
    ) -> tuple[int, int]:
        """
        验证ES中的数据存在

        Args:
            es_client: ES客户端
            index_prefix: 索引前缀
            expected_filename: 期望的文件名

        Returns:
            tuple: (metadata_count, chunk_count)
        """
        metadata_index = self._get_metadata_index_name(index_prefix)
        chunk_index = self._get_chunk_index_name(index_prefix)

        # 刷新索引确保数据可见
        es_client.indices.refresh(index=[metadata_index, chunk_index])

        # 检查metadata索引
        metadata_response = es_client.search(
            index=metadata_index,
            body={"query": {"match": {"name": expected_filename}}, "size": 10},
        )
        metadata_count = len(metadata_response["hits"]["hits"])

        # 检查chunk索引
        chunk_response = es_client.search(
            index=chunk_index, body={"query": {"match_all": {}}, "size": 100}
        )
        chunk_count = len(chunk_response["hits"]["hits"])

        return metadata_count, chunk_count

    def _cleanup_es_indexes(
        self, es_client: Elasticsearch, index_prefix: str
    ) -> None:
        """
        清理测试索引

        Args:
            es_client: ES客户端
            index_prefix: 索引前缀
        """
        metadata_index = self._get_metadata_index_name(index_prefix)
        chunk_index = self._get_chunk_index_name(index_prefix)

        try:
            if es_client.indices.exists(index=metadata_index):
                es_client.indices.delete(index=metadata_index)
            if es_client.indices.exists(index=chunk_index):
                es_client.indices.delete(index=chunk_index)
            print(f"✅ 已清理索引: {metadata_index}, {chunk_index}")
        except Exception as e:
            print(f"⚠️ 清理索引时出错: {e}")

    def _wait_for_es_data(
        self,
        es_client: Elasticsearch,
        index_prefix: str,
        expected_filename: str,
        max_wait_time: int = 15,
        wait_interval: int = 2,
    ) -> tuple[int, int]:
        """
        等待ES数据就绪

        Args:
            es_client: ES客户端
            index_prefix: 索引前缀
            expected_filename: 期望的文件名
            max_wait_time: 最大等待时间(秒)
            wait_interval: 检查间隔(秒)

        Returns:
            tuple: (metadata_count, chunk_count)
        """
        print(f"⏳ 等待数据处理完成... (最多等待{max_wait_time}秒)")

        for attempt in range(max_wait_time // wait_interval):
            time.sleep(wait_interval)

            try:
                metadata_count, chunk_count = self._verify_es_data_exists(
                    es_client, index_prefix, expected_filename
                )

                if metadata_count > 0 and chunk_count > 0:
                    print("✅ ES验证成功!")
                    print(f"   📝 Metadata记录: {metadata_count}")
                    print(f"   📄 Chunk记录: {chunk_count}")
                    return metadata_count, chunk_count

            except Exception as e:
                print(f"⏳ 第{attempt + 1}次检查: 数据还未就绪 ({e})")

        # 最后一次验证
        metadata_count, chunk_count = self._verify_es_data_exists(
            es_client, index_prefix, expected_filename
        )

        return metadata_count, chunk_count

    def test_upload_file(
        self,
        client: TestClient,
        es_client: Elasticsearch,
        get_user_upload_file: Callable[[str], Path],
    ) -> None:
        """测试文件上传功能并验证ES存储结果"""

        test_file_name = "03_test.pdf"
        index_prefix = self.FILE_UPLOAD_INDEX_PREFIX

        print(f"\n📂 测试文件上传: {test_file_name}")
        print(f"📋 索引前缀: {index_prefix}")

        try:
            test_file_path = get_user_upload_file(test_file_name)
            if test_file_path.stat().st_size == 0:
                pytest.skip(f"请确保 {test_file_name} 是一个非空pdf文件\n")
        except FileNotFoundError:
            pytest.skip(
                f"测试文件 {test_file_name} 不存在，请放入 tests/fixtures/files/user/ 目录"
            )

        # 清理可能存在的旧数据
        self._cleanup_es_indexes(es_client, index_prefix)

        try:
            # 步骤1: 上传文件
            test_file = get_user_upload_file(test_file_name)

            with test_file.open("rb") as f:
                response = client.post(
                    "/api/v1/documents/upload-file",
                    files={"file": (test_file.name, f, "application/pdf")},
                    data={
                        "index_prefix": index_prefix,
                        "category": "test_document",
                        "tags": "pdf,test",
                    },
                )

            # 验证上传响应
            assert response.status_code == 200
            upload_result = response.json()
            assert "task_id" in upload_result
            assert "message" in upload_result
            print(f"✅ 文件上传成功，任务ID: {upload_result['task_id']}")

            # 步骤2: 等待异步处理完成并验证ES数据
            metadata_count, chunk_count = self._wait_for_es_data(
                es_client, index_prefix, test_file_name, max_wait_time=15
            )

            # 断言数据存在
            assert metadata_count > 0, (
                f"未找到metadata记录，索引: {self._get_metadata_index_name(index_prefix)}"
            )
            assert chunk_count > 0, (
                f"未找到chunk记录，索引: {self._get_chunk_index_name(index_prefix)}"
            )

            self._assert_task_endpoint(client)
            print("🎉 文件上传测试完成!")

        finally:
            # 清理测试数据
            self._cleanup_es_indexes(es_client, index_prefix)

    @staticmethod
    def _assert_task_endpoint(client: TestClient) -> None:
        resp = client.get("/api/v1/tasks/{upload_result['task_id']}")
        assert resp.status_code == 200
        task_result = resp.json()
        assert "task_id" in task_result
        assert "status" in task_result

    def test_upload_file_missing_index_prefix(self, client: TestClient) -> None:
        """测试文件上传缺少index_prefix参数的验证"""

        print("\n🛡️ 测试文件上传缺少index_prefix参数...")

        response = client.post(
            "/api/v1/documents/upload-file",
            files={"file": ("test.txt", "test content", "text/plain")},
            data={"category": "test"},  # 缺少index_prefix
        )

        # 验证返回：422错误(参数验证失败)
        assert response.status_code == 422
        error_detail = response.json()
        assert "detail" in error_detail

        print("✅ 文件上传缺少index_prefix参数验证通过!")

    def test_upload_file_empty_index_prefix(self, client: TestClient) -> None:
        """测试文件上传空index_prefix参数的验证"""

        print("\n🛡️ 测试文件上传空index_prefix参数...")

        response = client.post(
            "/api/v1/documents/upload-file",
            files={"file": ("test.txt", "test content", "text/plain")},
            data={"index_prefix": ""},  # 空字符串
        )

        # 验证返回422错误(参数验证失败)
        assert response.status_code == 422
        error_detail = response.json()
        assert "detail" in error_detail

        print("✅ 文件上传空index_prefix参数验证通过!")

    def test_upload_file_invalid_file(self, client: TestClient) -> None:
        """测试文件上传无效文件的处理"""

        print("\n🛡️ 测试文件上传无效文件...")

        # 发送空文件
        response = client.post(
            "/api/v1/documents/upload-file",
            files={"file": ("empty.txt", "", "text/plain")},
            data={"index_prefix": "test_invalid"},
        )

        # 验证返回400(立即拒绝)
        assert response.status_code == 400
        error_detail = response.json()
        assert "detail" in error_detail

        print("✅ 无效文件上传处理验证通过!")

    def test_upload_from_url(
        self,
        client: TestClient,
        es_client: Elasticsearch,
    ) -> None:
        """测试URL上传功能并验证ES存储结果"""

        index_prefix = self.URL_UPLOAD_INDEX_PREFIX
        object_key = "kbase-temp/02_test.pdf"
        bucket_name = settings.tencent_oss.bucket
        cos_url = f"https://{bucket_name}.cos.{settings.tencent_oss.region}.myqcloud.com/{object_key}"
        expected_filename = object_key.split("/")[-1]  # 从URL提取文件名

        print(f"\n🔗 测试URL上传: {cos_url}")
        print(f"📋 索引前缀: {index_prefix}")

        # 清理可能存在的旧数据
        self._cleanup_es_indexes(es_client, index_prefix)

        try:
            # 步骤1: 通过URL上传
            response = client.post(
                "/api/v1/documents/upload-from-url",
                json={
                    "url": cos_url,
                    "index_prefix": index_prefix,
                    "category": "test_url_document",
                    "tags": "pdf,url_test",
                },
            )

            # 验证上传响应
            assert response.status_code == 200
            upload_result = response.json()
            assert "task_id" in upload_result
            assert "message" in upload_result
            print(f"✅ URL上传成功，任务ID: {upload_result['task_id']}")

            # 步骤2: 等待异步处理完成并验证ES数据 (URL下载需要更长时间)
            metadata_count, chunk_count = self._wait_for_es_data(
                es_client,
                index_prefix,
                expected_filename,
                max_wait_time=20,
                wait_interval=3,
            )

            # 断言数据存在
            assert metadata_count > 0, (
                f"未找到metadata记录，索引: {self._get_metadata_index_name(index_prefix)}"
            )
            assert chunk_count > 0, (
                f"未找到chunk记录，索引: {self._get_chunk_index_name(index_prefix)}"
            )

            self._assert_task_endpoint(client)

            print("🎉 URL上传测试完成!")

        finally:
            # 清理测试数据
            self._cleanup_es_indexes(es_client, index_prefix)

    def test_upload_from_url_missing_index_prefix(
        self, client: TestClient
    ) -> None:
        """测试URL上传缺少index_prefix参数的验证"""

        print("\n🛡️ 测试URL上传缺少index_prefix参数...")

        response = client.post(
            "/api/v1/documents/upload-from-url",
            json={"url": "https://example.com/test.pdf"},  # 缺少index_prefix
        )

        # 验证返回：422错误(参数验证失败)
        assert response.status_code == 422
        error_detail = response.json()
        assert "detail" in error_detail

        print("✅ URL上传缺少index_prefix参数验证通过!")

    def test_upload_from_url_empty_index_prefix(
        self, client: TestClient
    ) -> None:
        """测试URL上传空index_prefix参数的验证"""

        print("\n🛡️ 测试URL上传空index_prefix参数...")

        response = client.post(
            "/api/v1/documents/upload-from-url",
            json={
                "url": "https://example.com/test.pdf",
                "index_prefix": "",  # 空字符串
            },
        )

        # 验证返回422错误(参数验证失败)
        assert response.status_code == 422
        error_detail = response.json()
        assert "detail" in error_detail

        print("✅ URL上传空index_prefix参数验证通过!")

    def test_upload_from_url_invalid_url(self, client: TestClient) -> None:
        """测试URL上传无效URL的验证"""

        print("\n🛡️ 测试URL上传无效URL...")

        response = client.post(
            "/api/v1/documents/upload-from-url",
            json={"url": "not-a-valid-url", "index_prefix": "test_invalid"},
        )

        # 验证返回422错误(URL格式验证失败)
        assert response.status_code == 422
        error_detail = response.json()
        assert "detail" in error_detail

        print("✅ 无效URL验证通过!")
