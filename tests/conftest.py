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

"""
API 测试配置和共享fixtures
"""

import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from elasticsearch import Elasticsearch
from fastapi.testclient import TestClient
from qcloud_cos import CosS3Client  # type: ignore[import-untyped]

from app.config.settings import settings
from app.main import app

# 确保测试存储目录存在
test_storage_path = Path(__file__).parent / "fixtures" / "files" / "uploaded"
test_storage_path.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def cos_client() -> CosS3Client:
    """
    腾讯云COS客户端 - 仅用于 @pytest.mark.cos 标记的测试
    """
    client = CosS3Client(settings.cos_config)
    client.list_buckets()
    logger.info("✅ 成功连接到腾讯云COS服务。")
    return client


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, Any, None]:
    """V2 API 测试客户端"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def es_client() -> Generator[Elasticsearch, Any, None]:
    """
    Elasticsearch客户端 - 用于测试ES相关操作
    """
    client = Elasticsearch(
        hosts=[{"host": "localhost", "port": 9200, "scheme": "http"}],
        request_timeout=100,
        retry_on_timeout=True,
        # 如果有认证信息也要添加
    )
    # 测试连接
    try:
        info = client.info()
        logger.info(
            f"✅ 成功连接到Elasticsearch服务: {info['version']['number']}"
        )
        yield client
    except Exception as e:
        logger.error(f"❌ 无法连接到Elasticsearch: {e}")
        pytest.fail("Elasticsearch服务不可用")
    finally:
        client.close()
