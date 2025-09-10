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

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)

# qcloud_cos 库没有提供类型存根 (stubs),
# 这会导致 mypy 无法分析其类型。我们添加 # type: ignore 来告知 mypy 跳过对这一行的检查。
from qcloud_cos import CosConfig  # type: ignore[import-untyped]

# 定义与 YAML 和 .env 文件结构匹配的 Pydantic 模型


class ElasticsearchSettings(BaseModel):
    """Elasticsearch 相关配置"""

    url: str
    metadata_index: str = "file_metadatas"
    chunk_index: str = "file_chunks"
    request_timeout: int = 15


class EmbedderSettings(BaseModel):
    """嵌入模型相关配置"""

    model_name: str
    dimensions: int
    similarity_metric: str
    index_type: str


class RerankerSettings(BaseModel):
    """重排模型相关配置"""

    model_name: str


class SplitterSettings(BaseModel):
    """文本切分相关配置"""

    chunk_size: int
    chunk_overlap: int


class StorageSettings(BaseModel):
    """本地存储相关配置"""

    local_path: str = Field(description="用于暂存上传文件的本地目录")


class UploadSettings(BaseModel):
    """文件上传限制相关配置"""

    max_file_size_mb: int = Field(
        50, description="允许上传的最大文件大小（单位：MB）"
    )
    supported_file_extensions: list[str] = Field(
        default=[".txt", ".md", ".pdf"], description="支持上传的文件扩展名列表"
    )


class RetrievalSettings(BaseModel):
    """召回相关配置"""

    multiplier: int = Field(5, description="召回倍数配置")
    vector_weight: float = Field(2.0, description="向量搜索权重")
    text_weight: float = Field(1.0, description="文本搜索权重")


class TencentOssSettings(BaseModel):
    """
    腾讯云对象存储相关配置。
    所有字段均为必需，如果未在.env文件中通过 TENCENT_OSS__SECRET_ID 等变量提供，应用将在启动时因验证失败而崩溃。
    """

    secret_id: str
    secret_key: str
    bucket: str
    region: str


class Settings(BaseSettings):
    """
    主设置类，聚合所有配置，并编排加载顺序。
    """

    # 直接声明它，而不使用 `default` 或 `default_factory`。
    # Pydantic 在初始化时会自动查找并验证以 `TENCENT_OSS__` 为前缀的环境变量。
    tencent_oss: TencentOssSettings

    # 来自 config.yaml 的常规配置。
    elasticsearch: ElasticsearchSettings
    embedder: EmbedderSettings
    reranker: RerankerSettings
    splitter: SplitterSettings
    storage: StorageSettings
    upload: UploadSettings
    retrieval: RetrievalSettings

    @property
    def cos_config(self) -> CosConfig:
        """
        根据原始配置动态创建并返回一个 `CosConfig` 对象。
        由于Pydantic的模型验证确保了`tencent_oss`及其所有字段都存在，这里无需进行任何检查。

        Returns:
            一个 `CosConfig` 实例。
        """
        print(self.tencent_oss)
        return CosConfig(
            Region=self.tencent_oss.region,
            SecretId=self.tencent_oss.secret_id,
            SecretKey=self.tencent_oss.secret_key,
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        env_file_encoding="utf-8",
    )


def create_settings() -> Settings:
    """
    创建设置实例的工厂函数。
    根据环境选择合适的配置文件，然后创建 Settings 实例。
    """
    import sys

    # 检测是否在测试环境中
    is_testing = "pytest" in sys.modules or any(
        "test" in arg.lower() for arg in sys.argv
    )

    # 根据环境选择配置文件
    project_root = Path(__file__).parent.parent.parent
    if is_testing:
        config_path = project_root / "tests" / "fixtures" / "config.yaml"
        config_type = "测试"
    else:
        config_path = project_root / "config.yaml"
        config_type = "生产"

    yaml_config: dict[str, Any] = {}

    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as f:
                yaml_config = yaml.safe_load(f) or {}
                print(f"✅ 成功加载 {config_type} YAML 配置文件: {config_path}")
                print(f"   配置字段: {list(yaml_config.keys())}")
        except Exception as e:
            print(f"❌ 读取 {config_type} YAML 配置文件失败: {e}")
    else:
        print(f"⚠️ {config_type} YAML 配置文件不存在: {config_path}")
        # 如果测试配置文件不存在，回退到生产配置文件
        if is_testing:
            fallback_path = project_root / "config.yaml"
            if fallback_path.is_file():
                try:
                    with open(fallback_path, encoding="utf-8") as f:
                        yaml_config = yaml.safe_load(f) or {}
                        print(f"🔄 回退使用生产配置文件: {fallback_path}")
                except Exception as e:
                    print(f"❌ 回退配置文件也读取失败: {e}")

    # 创建设置实例，传递 YAML 配置
    try:
        return Settings(**yaml_config)
    except Exception as e:
        print(f"❌ 使用 YAML 配置创建 Settings 失败: {e}")
        print("   这通常意味着配置文件不完整或环境变量缺失")
        raise RuntimeError("配置文件加载失败，请检查配置") from e


# 创建并导出全局单例。
settings = create_settings()
