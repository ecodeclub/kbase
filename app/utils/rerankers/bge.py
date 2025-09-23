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

from app.domain.search import ContextChunk


class BgeReranker:
    """
    使用 BAAI/bge-reranker-base 模型进行重排序的重排器。
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base") -> None:
        """
        :param model_name: CrossEncoder 模型的名称。
        """
        from sentence_transformers import CrossEncoder

        # 仅在实际需要时加载模型，可以加速应用启动
        # 也可以在这里传入 device='cuda' 等参数
        self.model = CrossEncoder(model_name)
        print(f"BGE Reranker loaded with model: {model_name}")

    def rerank(
        self, query: str, results: list[ContextChunk]
    ) -> list[ContextChunk]:
        if not query or not results:
            return results

        # 创建副本，避免修改原始对象
        results_copy = [
            ContextChunk(
                text=chunk.text,
                file_metadata_id=chunk.file_metadata_id,
                score=chunk.score,
            )
            for chunk in results
        ]

        # 使用模型计算得分
        # show_progress_bar=False 在生产环境中是很好的实践
        sentence_pairs = [[query, chunk.text] for chunk in results_copy]
        scores = self.model.predict(sentence_pairs, show_progress_bar=False)

        # 将新的 rerank 分数附加到每个 chunk 上
        for chunk, score in zip(results, scores, strict=True):
            chunk.score = float(score)

        # 根据新的 rerank 分数降序排序
        results.sort(key=lambda x: x.score, reverse=True)

        return results
