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

import os

from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    UnstructuredMarkdownLoader,
)
from langchain_core.documents import Document as LangChainDocument

from app.domain.document import Document


class DispatcherLoader:
    """DispatcherLoader 根据文件后缀分发到正确的Loader。"""

    @staticmethod
    def load(document: Document) -> list[LangChainDocument]:
        # 添加文件存在性检查
        if not os.path.exists(document.path):
            raise FileNotFoundError(f"文件不存在: {document.path}")

        ext = os.path.splitext(document.path)[1].lower()
        # 获取 loader 特定的参数，提供默认值
        loader_args = document.loader_args or {}
        if ext == ".txt":
            args = loader_args.get("txt", {"encoding": "utf-8"})
            return TextLoader(document.path, encoding=args["encoding"]).load()
        elif ext == ".md":
            # 如果 'markdown_load_args' 未提供，则默认为 'elements'
            args = loader_args.get("markdown", {"mode": "elements"})
            return UnstructuredMarkdownLoader(
                document.path, mode=args["mode"]
            ).load()
        elif ext == ".pdf":
            args = loader_args.get("pdf", {})
            return PyPDFLoader(document.path, **args).load()
        else:
            raise ValueError(f"不支持的文件类型: {ext}")
