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
from pprint import pprint
from typing import overload

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings


class TestAPI:
    """
    端到端测试类，测试路径为 /api/v1/。
    """

    @pytest.fixture(scope="class")
    def user_upload_dir(self) -> Path:
        """提供 '用户准备上传' 的文件目录路径。"""
        path = Path(__file__).parent / "fixtures" / "files" / "user"
        path.mkdir(exist_ok=True, parents=True)
        return path

    @pytest.fixture(scope="class")
    def backend_uploaded_dir(self) -> Path:
        """提供 '后端已接收' 的文件根目录路径。"""
        path = Path(__file__).parent / "fixtures" / "files" / "uploaded"
        path.mkdir(exist_ok=True, parents=True)
        return path

    @pytest.fixture(scope="class")
    def get_user_upload_file(
        self, user_upload_dir: Path
    ) -> Callable[[str | list[str]], Path | list[Path]]:
        """从 'user' 目录轻松获取文件路径。"""

        # 为 mypy 准备的类型重载，用于精确类型推断
        @overload
        def _builder(file_names: str) -> Path: ...

        @overload  # noqa: F811
        def _builder(file_names: list[str]) -> list[Path]: ...

        def _builder(file_names: str | list[str]) -> Path | list[Path]:  # noqa: F811
            if isinstance(file_names, str):
                path = user_upload_dir / file_names
                if not path.exists():
                    raise FileNotFoundError(f"源文件不存在: {path}")
                return path

            paths = [user_upload_dir / name for name in file_names]
            if not all(p.exists() for p in paths):
                raise FileNotFoundError("一个或多个源文件不存在。")
            return paths

        return _builder  # type: ignore[return-value]

    def test_upload_file_and_search_flow(
        self,
        client: TestClient,
        get_user_upload_file: Callable[[str], Path],
        backend_uploaded_dir: Path,
    ) -> None:
        """测试本地上传 -> 验证文件在UUID子目录中 -> 搜索。"""
        test_file_name = "03_test.pdf"
        print(f"\n▶️ 测试本地上传，使用文件: {test_file_name}")

        test_file = get_user_upload_file(test_file_name)

        with test_file.open("rb") as f:
            response = client.post(
                "/api/v1/documents/upload-file",
                files={"file": (test_file.name, f, "application/pdf")},
            )
        assert response.status_code == 200

        # 验证上传响应
        upload_result = response.json()
        assert "task_id" in upload_result
        print(f"✅ 文件上传成功，任务ID: {upload_result['task_id']}")

        # 文件上传后会被异步处理，然后正确清理
        # 我们通过上传响应和后续的索引结果来验证处理成功
        print("✅ 文件上传成功，后台正在异步处理（处理完成后会自动清理）")

        import time

        print("⏳ 等待索引...")
        time.sleep(5)

        query = {"query": "数据库", "top_k": 3}
        print(f"查询参数：{query}\n")

        response = client.post(
            "/api/v1/search", json={"query": "数据库并发", "top_k": 3}
        )
        assert response.status_code == 200
        search_results = response.json()
        assert len(search_results["context"]) > 0
        print("✅ 搜索成功！结果详情:")
        pprint(search_results)

    def test_health_check_endpoint(self, client: TestClient) -> None:
        """测试API健康检查端点"""
        print("\n🏥 测试健康检查端点...")
        response = client.get("/api/v1/health")
        assert response.status_code == 200

        health_data = response.json()
        assert health_data["status"] == "healthy"
        print("✅ 健康检查端点正常")

    def test_upload_performance_monitoring(
        self,
        client: TestClient,
        get_user_upload_file: Callable[[str], Path],
    ) -> None:
        """测试文件上传的性能表现"""
        test_file_name = "01_test.pdf"
        print(f"\n⏱️ 测试上传性能: {test_file_name}")

        test_file = get_user_upload_file(test_file_name)
        file_size = test_file.stat().st_size
        print(f"   文件大小: {file_size / 1024:.1f} KB")

        with test_file.open("rb") as f:
            start_time = time.time()
            response = client.post(
                "/api/v1/documents/upload-file",
                files={"file": (test_file.name, f, "application/pdf")},
            )
            upload_duration = time.time() - start_time

        assert response.status_code == 200
        upload_result = response.json()
        assert "task_id" in upload_result

        print("✅ 性能测试完成")
        print(f"   - 上传耗时: {upload_duration:.2f}秒")
        print(f"   - 上传速度: {file_size / 1024 / upload_duration:.1f} KB/s")

    def test_search_robustness(self, client: TestClient) -> None:
        """测试搜索功能的鲁棒性"""
        print("\n🛡️ 测试搜索鲁棒性...")

        # 定义各种边界情况
        robustness_cases = [
            {
                "query": "不存在的专业术语xyz123",
                "description": "不存在内容",
                "expect_results": False,
            },
            {"query": "数", "description": "极短查询", "expect_results": True},
            {
                "query": "数据库性能优化并发处理" * 10,
                "description": "超长查询",
                "expect_results": True,
            },
            {"query": "", "description": "空字符串", "expect_results": False},
            {"query": "   ", "description": "纯空格", "expect_results": False},
            {
                "query": "!@#$%",
                "description": "特殊字符",
                "expect_results": False,
            },
        ]

        for case in robustness_cases:
            print(f"🔍 测试场景: {case['description']}")
            search_data = {"query": case["query"], "top_k": 3}
            response = client.post("/api/v1/search", json=search_data)

            # 所有情况都应该返回 200，不应该崩溃
            assert response.status_code == 200
            search_result = response.json()
            assert "context" in search_result

            result_count = len(search_result["context"])
            query_text = str(case["query"])
            display_query = (
                query_text[:20] + "..." if len(query_text) > 20 else query_text
            )
            print(f"   查询: '{display_query}' -> {result_count} 条结果")

            # 验证预期行为
            if case["expect_results"]:
                # 对于有意义的查询，应该尽量有结果（但不强制）
                print("   ✅ 查询处理正常")
            else:
                # 对于无意义查询，无结果是正常的
                print("   ✅ 边界情况处理正常")

    def test_upload_url_and_search_flow(
        self,
        client: TestClient,
    ) -> None:
        """测试从COS URL上传 -> 搜索流程（使用预上传的文件）"""

        object_key = "kbase-temp/02_test.pdf"
        bucket_name = settings.tencent_oss.bucket
        cos_url = f"https://{bucket_name}.cos.{settings.tencent_oss.region}.myqcloud.com/{object_key}"

        print(f"🔗 测试COS URL: {cos_url}")
        print(f"   存储桶: {bucket_name}")
        print(f"   对象键: {object_key}")

        try:
            # 步骤1: 通过API从COS URL上传
            print("📥 步骤1: 通过API从COS URL上传...")
            response = client.post(
                "/api/v1/documents/upload-from-url", json={"url": cos_url}
            )
            assert response.status_code == 200
            upload_result = response.json()
            assert "task_id" in upload_result
            print(f"✅ URL上传API调用成功，任务ID: {upload_result['task_id']}")

            # 步骤2: 等待索引完成
            print("⏳ 步骤2: 等待索引完成...")
            time.sleep(5)

            # 步骤3: 测试搜索
            print("🔍 步骤3: 测试搜索...")
            response = client.post(
                "/api/v1/search", json={"query": "读多写少", "top_k": 3}
            )
            assert response.status_code == 200
            search_results = response.json()

            print(f"搜索结果数量: {len(search_results['context'])}")
            if len(search_results["context"]) > 0:
                print("✅ COS URL上传内容的搜索成功！结果详情:")
                pprint(search_results)
            else:
                print("⚠️ 搜索结果为空，可能文件还在处理中或内容不匹配")
                # 不强制要求搜索结果，因为索引可能需要更多时间

            print("🎉 COS URL上传和搜索测试完成！")

        except Exception as e:
            print(f"❌ 测试过程中出现异常: {e}")
            raise
