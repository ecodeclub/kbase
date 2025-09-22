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

from fastapi.testclient import TestClient


class TestHealthEndpoint:
    def test_health_check_endpoint(self, client: TestClient) -> None:
        """测试API健康检查端点"""
        print("\n🏥 测试健康检查端点...")
        response = client.get("/api/v1/health")
        assert response.status_code == 200

        health_data = response.json()
        assert health_data["status"] == "healthy"
        print("✅ 健康检查端点正常")
