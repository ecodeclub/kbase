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

import asyncio
import logging
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlparse

from elasticsearch import NotFoundError
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
)

# qcloud_cos 库没有提供类型存根 (stubs),
# 这会导致 mypy 无法分析其类型。我们添加 # type: ignore 来告知 mypy 跳过对这一行的检查。
from qcloud_cos import CosS3Client  # type: ignore[import-untyped]

from app.config.settings import Settings
from app.domain.document import Document
from app.service.elasticsearch import ElasticsearchService
from app.utils.converters import SearchConverter
from app.web.vo import (
    FileUploadResponse,
    SaveRequest,
    SaveResponse,
    SearchRequest,
    SearchResponse,
    UrlUploadRequest,
    UrlUploadResponse,
)

logger = logging.getLogger(__name__)


class DocumentHandler:
    """
    文档处理器 - 集成腾讯云COS，并采用自注册路由模式。
    """

    def __init__(
        self,
        router: APIRouter,
        search_service: ElasticsearchService,
        settings: Settings,
        cos_client: CosS3Client | None,
    ) -> None:
        """
        初始化处理器

        Args:
            router: FastAPI的路由器实例，用于注册本处理器的API端点。
            search_service: 核心的Elasticsearch服务实例。
            settings: 应用的全局配置对象。
            cos_client: 腾讯云COS客户端实例（可能为None）。
        """
        self._router = router
        self._service = search_service
        self._settings = settings
        self._cos_client = cos_client
        self._storage_path = Path(settings.storage.local_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._max_file_size_bytes = (
            settings.upload.max_file_size_mb * 1024 * 1024
        )
        self._supported_file_extensions = set(
            settings.upload.supported_file_extensions
        )
        self._task_status: dict[str, str] = {}

    def register_routes(self) -> None:
        self._router.get("/hello", summary="健康检查接口")(
            lambda: {"message": "Hello, KBase RAG!"}
        )
        """将本处理器中的所有API端点注册到构造时传入的路由器上。"""

        self._router.get("/health", summary="健康检查")(DocumentHandler.health)

        self._router.get(
            "/tasks/{task_id}",
            summary="查询任务状态",
        )(self.get_task_status)

        self._router.post(
            "/documents/upload-file",
            response_model=FileUploadResponse,
            summary="通过文件上传进行索引，可以假定索引已提前建好，只需要用前后缀拼接得到完整索引名称即可",
        )(self.upload_file)

        self._router.post(
            "/documents/upload-from-url",
            response_model=UrlUploadResponse,
            summary="通过腾讯云COS URL下载并进行索引，可以假定索引已提前建好，只需要用前后缀拼接得到完整索引名称即可",
        )(self.upload_from_url)

        self._router.post(
            "/search",
            response_model=SearchResponse,
            summary="在知识库中进行搜索",
        )(self.search)

        self._router.post(
            "/documents/save",
            response_model=SaveResponse,
            summary="保存JSON格式文档到指定的Elasticsearch索引",
        )(self.save)

    @staticmethod
    async def health() -> dict[str, str]:
        """健康检查接口。"""
        return {"status": "healthy"}

    async def get_task_status(self, task_id: str) -> dict[str, str]:
        """查询任务状态"""
        status = self._task_status.get(task_id, "not_found")
        return {"task_id": task_id, "status": status}

    def _process_and_cleanup(
        self, task_id: str, temp_dir: Path, document: Document
    ) -> None:
        """后台任务函数：执行索引存储，并在完成后清理临时文件。"""
        self._task_status[task_id] = "processing"
        try:
            logger.info(f"后台任务开始处理: {document.path}")
            self._service.store_for_vector_hybrid_search(document)
            logger.info(f"✅ 后台任务成功处理文件: {document.path}")
            self._task_status[task_id] = "completed"
        except Exception as e:
            logger.error(
                f"❌ 后台任务处理失败: {document.path}, 错误: {e}",
                exc_info=True,
            )
            self._task_status[task_id] = f"failed: {str(e)}"
        finally:
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"🧹 已清理临时目录: {temp_dir}")
            except OSError as e:
                logger.error(f"❌ 清理临时目录失败: {temp_dir}, 错误: {e}")

    async def _cleanup_task_status(
        self, task_id: str, delay_seconds: int
    ) -> None:
        """延迟清理任务状态"""
        await asyncio.sleep(delay_seconds)
        if task_id in self._task_status:
            del self._task_status[task_id]
            logger.info(f"🧹 已清理任务状态: {task_id}")

    async def upload_file(
        self,
        background_tasks: BackgroundTasks,
        index_prefix: str = Form(
            ..., min_length=1, description="索引完整名称前缀"
        ),
        file: UploadFile = File(..., description="上传的文件"),
        category: str | None = Form(None, description="分类"),
        tags: str | None = Form(None, description="标签"),
    ) -> FileUploadResponse:
        """从用户上传的文件创建并索引文档"""
        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        # 验证文件名安全性
        if (
            ".." in file.filename
            or "/" in file.filename
            or "\\" in file.filename
        ):
            raise HTTPException(status_code=400, detail="文件名包含非法字符")

        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in self._supported_file_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {file_ext}。支持的格式: {self._supported_file_extensions}",
            )

        # 先检查文件大小（避免读取大文件到内存）
        if file.size and file.size > self._max_file_size_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件过大，最大支持{self._max_file_size_bytes // 1024 // 1024}MB",
            )

        task_id = str(uuid.uuid4())
        temp_dir = self._storage_path / task_id
        temp_dir.mkdir(parents=True, exist_ok=True)
        file_path = temp_dir / file.filename

        try:
            content = await file.read()

            if len(content) == 0:
                shutil.rmtree(temp_dir)
                raise HTTPException(status_code=400, detail="不能上传空文件")

            # 双重检查（防止file.size不准确的情况）
            if len(content) > self._max_file_size_bytes:
                shutil.rmtree(temp_dir)
                raise HTTPException(
                    status_code=413,
                    detail=f"文件过大，最大支持{self._max_file_size_bytes // 1024 // 1024}MB",
                )
            file_path.write_bytes(content)
            file_size = file_path.stat().st_size
        except HTTPException:
            raise
        except Exception as e:
            shutil.rmtree(temp_dir)
            logger.error(f"保存上传文件失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail="保存上传文件失败"
            ) from e

        tag_list = [tag.strip() for tag in tags.split(",")] if tags else []
        document = Document(
            index_prefix=index_prefix,
            path=str(file_path.resolve()),
            size=file_size,
            category=category,
            tags=tag_list,
        )
        background_tasks.add_task(
            self._process_and_cleanup, task_id, temp_dir, document
        )
        return FileUploadResponse(task_id=task_id, message="ok")

    def _validate_and_parse_cos_url(self, url: str) -> tuple[str, str]:
        """
        验证并解析COS URL

        Returns:
            tuple[cos_key, filename]: COS对象键和文件名
        """
        try:
            parsed_url = urlparse(url)

            # 验证URL域名安全性（防止SSRF攻击）
            expected_domain = f"{self._settings.tencent_oss.bucket}.cos.{self._settings.tencent_oss.region}.myqcloud.com"
            if parsed_url.netloc != expected_domain:
                raise HTTPException(
                    status_code=400,
                    detail=f"URL必须来自配置的COS存储桶域名: {expected_domain}",
                )

            cos_key = parsed_url.path.lstrip("/")
            if not cos_key:
                raise HTTPException(status_code=400, detail="URL路径不能为空")

            filename = Path(cos_key).name

            # 验证文件名安全性（防止路径遍历）
            if ".." in filename or not filename:
                raise HTTPException(
                    status_code=400, detail="文件名包含非法字符或为空"
                )

            # 验证文件扩展名
            file_ext = Path(filename).suffix.lower()
            if file_ext not in self._supported_file_extensions:
                raise HTTPException(
                    status_code=400,
                    detail=f"不支持的文件类型: {file_ext}。支持的格式: {self._supported_file_extensions}",
                )

            return cos_key, filename

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"无效的URL格式: {e}"
            ) from e

    async def _get_cos_object_metadata(
        self, cos_key: str
    ) -> tuple[int, str | None, list[str]]:
        """
        获取COS对象元数据

        Returns:
            tuple[file_size, category, tag_list]: 文件大小、类别和标签列表
        """
        try:
            # mypy会抱怨self._cos_client可能为None，但我们在调用前已经检查过了
            metadata = await asyncio.to_thread(
                self._cos_client.head_object,  # type: ignore[union-attr]
                Bucket=self._settings.tencent_oss.bucket,
                Key=cos_key,
            )

            # 安全地获取文件大小
            content_length = metadata.get("Content-Length", "0")
            try:
                file_size = int(content_length) if content_length else 0
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=502, detail="COS返回的文件大小格式无效"
                ) from None

            category = metadata.get("x-cos-meta-category")
            tags_str = metadata.get("x-cos-meta-tags")
            tag_list = (
                [tag.strip() for tag in tags_str.split(",")] if tags_str else []
            )

            return file_size, category, tag_list

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取COS对象元数据失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"获取COS对象元数据失败: {cos_key}",
            ) from e

    async def _download_cos_file(
        self, cos_key: str, file_path: Path, temp_dir: Path
    ) -> None:
        """
        从COS下载文件到本地路径

        Args:
            cos_key: COS对象键
            file_path: 本地文件路径
            temp_dir: 临时目录（出错时用于清理）
        """
        try:
            await asyncio.to_thread(
                self._cos_client.download_file,  # type: ignore[union-attr]
                Bucket=self._settings.tencent_oss.bucket,
                Key=cos_key,
                DestFilePath=str(file_path),
            )
        except Exception as e:
            shutil.rmtree(temp_dir)
            logger.error(f"从COS下载文件失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"从COS下载文件失败：{cos_key}"
            ) from e

    async def upload_from_url(
        self, request: UrlUploadRequest, background_tasks: BackgroundTasks
    ) -> UrlUploadResponse:
        """从腾讯云COS URL下载文件，然后创建并索引文档。"""
        # 0. 检查COS客户端是否可用
        if self._cos_client is None:
            raise HTTPException(
                status_code=503,
                detail="COS服务不可用，请检查COS客户端配置或联系管理员",
            )

        # 1. 验证并解析URL
        cos_key, filename = self._validate_and_parse_cos_url(str(request.url))

        # 2. 获取COS对象元数据
        file_size, category, tag_list = await self._get_cos_object_metadata(
            cos_key
        )

        # 3. 准备临时目录和文件路径
        task_id = str(uuid.uuid4())
        temp_dir = self._storage_path / task_id
        temp_dir.mkdir(parents=True, exist_ok=True)
        file_path = temp_dir / filename

        # 4. 下载文件
        await self._download_cos_file(cos_key, file_path, temp_dir)

        # 5. 如果无法从COS获取文件大小（权限不足），从本地文件获取
        if file_size == 0:
            file_size = file_path.stat().st_size
            logger.info(f"从本地文件获取实际大小: {file_size} 字节")

        # 6. 验证文件大小
        if file_size > self._max_file_size_bytes:
            shutil.rmtree(temp_dir)  # 清理已下载的文件
            raise HTTPException(
                status_code=413,
                detail=f"文件过大，最大支持{self._max_file_size_bytes // 1024 // 1024}MB",
            )

        # 7. 创建Document并添加后台任务
        document = Document(
            index_prefix=request.index_prefix,
            path=str(file_path.resolve()),
            size=file_size,
            category=category,
            tags=tag_list,
        )
        background_tasks.add_task(
            self._process_and_cleanup, task_id, temp_dir, document
        )
        return UrlUploadResponse(task_id=task_id, message="ok")

    async def search(self, request: SearchRequest) -> SearchResponse:
        """文档搜索接口"""
        try:
            logger.info(
                f"🔍 收到搜索请求: type='{request.type}', query='{request.query}', top_k={request.top_k}"
            )

            domain_response = self._service.search(
                SearchConverter.request_vo_to_domain(request)
            )

            resp = SearchConverter.result_domain_to_vo(
                domain_response, request.type
            )
            logger.info(
                f"✅ 搜索完成, 返回{len(domain_response.documents)}条结果"
            )
            return resp
        except NotFoundError as e:
            raise HTTPException(
                status_code=404, detail=f"索引 {request.query.index} 不存在"
            ) from e
        except Exception as e:
            logger.error(f"❌ 搜索失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="搜索处理失败") from e

    async def save(self, request: SaveRequest) -> SaveResponse:
        """保存JSON格式文档到指定的Elasticsearch索引"""
        try:
            self._service.save_for_structured_search(
                index_name=request.index,
                doc_id=request.key,
                doc_dict=request.doc_json,
            )
            return SaveResponse(message="ok")

        except ValueError as e:
            # JSON格式验证错误（由Pydantic自动处理）
            logger.error(f"JSON格式验证失败: {e}")
            raise HTTPException(
                status_code=400, detail=f"JSON格式错误: {str(e)}"
            ) from e

        except RuntimeError as e:
            # service层抛出的存储错误
            logger.error(f"文档存储失败: {e}")
            raise HTTPException(
                status_code=500, detail="文档存储失败，请稍后重试"
            ) from e

        except Exception as e:
            # 其他未预期的异常
            logger.error(f"保存文档时发生未知错误: {e}")
            raise HTTPException(status_code=500, detail="服务内部错误") from e
