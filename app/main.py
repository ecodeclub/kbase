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
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from elasticsearch import Elasticsearch

# 【修复】从 fastapi 导入 Request
from fastapi import APIRouter, FastAPI, Request
from qcloud_cos import CosS3Client  # type: ignore[import-untyped]

from app.config.settings import settings
from app.service.elasticsearch import ElasticsearchService
from app.utils.embedders.sentence_transformer import SentenceTransformerEmbedder
from app.utils.loaders.dispatcher import DispatcherLoader
from app.utils.rerankers.bge import BgeReranker
from app.utils.splitters import RecursiveCharacterTextSplitter
from app.web.handler import DocumentHandler

# 配置标准日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 严格初始化所有服务和依赖
try:
    logger.info("正在初始化核心服务组件 (Elasticsearch, Models)...")
    es_client = Elasticsearch(
        hosts=[settings.elasticsearch.url],
        request_timeout=settings.elasticsearch.request_timeout,
    )
    embedder = SentenceTransformerEmbedder(
        model_name=settings.embedder.model_name,
        similarity=settings.embedder.similarity_metric,
    )
    reranker = BgeReranker(model_name=settings.reranker.model_name)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.splitter.chunk_size,
        chunk_overlap=settings.splitter.chunk_overlap,
    )
    loader = DispatcherLoader()
    es_service = ElasticsearchService(
        client=es_client,
        loader=loader,
        splitter=splitter,
        embedder=embedder,
        reranker=reranker,
        metadata_index=settings.elasticsearch.metadata_index,
        chunk_index=settings.elasticsearch.chunk_index,
        settings=settings,
    )
    logger.info("✅ 核心服务组件初始化成功。")
except Exception as e:
    logger.critical(
        f"❌ 核心服务组件初始化失败，应用无法启动: {e}", exc_info=True
    )
    raise RuntimeError("核心服务组件初始化失败，应用无法启动") from e

# 检测是否在测试环境中（多种方法）
is_testing = (
    "pytest" in sys.modules
    or os.environ.get("PYTEST_CURRENT_TEST")
    or os.environ.get("_PYTEST_TMPDIR")
    or "test" in sys.argv[0].lower()
)

try:
    logger.info("正在初始化腾讯云COS客户端...")
    cos_config = settings.cos_config
    print(cos_config)
    cos_client = CosS3Client(cos_config)
except Exception as e:
    logger.critical(
        f"❌ 腾讯云COS客户端初始化失败 (请检查密钥、存储桶、区域或网络连接): {e}",
        exc_info=True,
    )
    raise RuntimeError(
        "腾讯云COS客户端初始化失败 (请检查密钥、存储桶、区域或网络连接)"
    ) from e

# 组装Web层和API路由
logger.info("正在组装Web层和API路由...")
api_router_v2 = APIRouter()
document_handler_v2 = DocumentHandler(
    router=api_router_v2,
    search_service=es_service,
    settings=settings,
    cos_client=cos_client,
)
document_handler_v2.register_routes()
logger.info("✅ API路由注册完成。")


# 应用生命周期管理
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """应用启动和关闭时的生命周期事件。"""
    logger.info("=" * 50)
    logger.info("🚀 KBase RAG API v0.1 正在启动...")
    logger.info("-" * 50)
    logger.info("当前生效配置:")
    logger.info(f"  - ES服务器: {settings.elasticsearch.url}")
    logger.info(f"  - 嵌入模型: {settings.embedder.model_name}")
    logger.info(f"  - 重排模型: {settings.reranker.model_name}")
    logger.info(f"  - 暂存目录: {settings.storage.local_path}")
    logger.info(f"  - 最大文件: {settings.upload.max_file_size_mb} MB")
    logger.info(f"  - 支持类型: {settings.upload.supported_file_extensions}")
    logger.info("  - 腾讯云COS:")
    logger.info(f"    - 区域: {settings.tencent_oss.region}")
    logger.info("-" * 50)
    logger.info("✅ 应用启动成功，等待请求...")
    yield
    logger.info("=" * 50)
    logger.info("🛑 KBase RAG API 正在关闭...")
    logger.info("=" * 50)


# 创建FastAPI应用实例
app = FastAPI(
    title="KBase RAG API",
    description="基于Elasticsearch的RAG知识库系统",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# 包含已配置好的路由
app.include_router(api_router_v2, prefix="/api/v1", tags=["RAG API v1"])


# 定义根路径端点
@app.get("/", tags=["Default"])
async def root(request: Request) -> dict[str, str]:
    """
    API根路径，提供基本信息和文档链接。
    通过依赖注入的 `request` 对象来安全地访问应用实例(`app`)的属性。
    """
    return {
        "message": "Welcome to KBase RAG API",
        # 使用 request.app 来访问应用实例的属性，这是FastAPI的推荐做法
        "version": request.app.version,
        "docs_url": str(request.app.docs_url),
    }
