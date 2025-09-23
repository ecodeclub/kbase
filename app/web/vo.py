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

"""Web层VO模型定义"""

from pydantic import BaseModel, Field, HttpUrl


class UrlUploadRequest(BaseModel):
    """从URL上传的请求体模型"""

    url: HttpUrl = Field(..., description="要下载和索引的文件的完整URL")


class FileUploadResponse(BaseModel):
    """文件上传后的标准响应模型"""

    task_id: str = Field(
        ..., description="本次上传任务的唯一ID，用于追踪和调试"
    )
    message: str = Field(
        "文件已接收，正在后台处理中...", description="操作结果信息"
    )


class UrlUploadResponse(BaseModel):
    """从URL上传后的标准响应模型"""

    task_id: str = Field(
        ..., description="本次上传任务的唯一ID，用于追踪和调试"
    )
    message: str = Field(
        "URL已接收，正在后台下载和处理中...", description="操作结果信息"
    )
