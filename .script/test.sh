#!/bin/bash

# 支持中文的测试脚本
BASE_URL="http://localhost:8080/api/v1"

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Python 辅助函数 - 正确显示中文
json_format() {
    python3 -c "
import json, sys
try:
    data = json.loads(sys.stdin.read())
    print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception as e:
    print(f'JSON解析错误: {e}')
    print('原始内容:', sys.stdin.read())
"
}

echo "🚀 快速测试 KBase RAG API"
echo "=========================="

# 查找PDF文件
PDF_FILE=$(find "$PROJECT_ROOT/tests/fixtures/files/user" -name "*.pdf" | head -1)

if [[ -z "$PDF_FILE" ]]; then
    echo "❌ 未找到PDF文件，请在 tests/fixtures/files/user 下放置测试PDF"
    exit 1
fi

echo "📄 测试文件: $PDF_FILE"
echo

# 1. 健康检查
echo "💓 健康检查..."
curl --noproxy "*" -s "$BASE_URL/health" | json_format
echo

# 2. 上传文件
echo "📤 上传文件..."
echo "正在上传: $(basename "$PDF_FILE")"

UPLOAD_RESPONSE=$(curl --noproxy "*" -s -X POST -F "file=@$PDF_FILE" "$BASE_URL/documents/upload-file")
echo "$UPLOAD_RESPONSE" | json_format

# 检查上传是否成功
SUCCESS=$(echo "$UPLOAD_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print('✅ 上传成功!' if data.get('message') else '❌ 上传失败!')
    print(f'📄 任务ID: {data.get(\"task_id\", \"N/A\")}')
except Exception as e:
    print(f'❌ 响应解析失败: {e}')
")

echo "$SUCCESS"
echo

echo "⏱️  等待3秒让索引完成..."
sleep 3

# 3. 搜索测试 - 使用中文查询
echo "🔍 搜索测试..."

QUERIES=("并发")

for query in "${QUERIES[@]}"; do
    echo
    echo "🔎 搜索查询: \"$query\""

    SEARCH_RESPONSE=$(curl --noproxy "*" -s -X POST \
      -H "Content-Type: application/json" \
      -d "{\"query\": \"$query\", \"top_k\": 2}" \
      "$BASE_URL/search")

    echo "原始响应:"
    echo "$SEARCH_RESPONSE" | json_format

    # 解析搜索结果 - 根据实际的SearchResponse和ContextChunk结构
    echo "$SEARCH_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    context = data.get('context', [])

    print(f'')
    print(f'📊 搜索结果摘要:')
    print(f'  🔎 查询词: \"$query\"')
    print(f'  📝 结果数量: {len(context)} 条')

    for i, item in enumerate(context[:2], 1):
        score = item.get('score', 0)
        file_id = item.get('file_metadata_id', 'Unknown')
        text_content = item.get('text', '')[:100]

        print(f'')
        print(f'  结果 {i}:')
        print(f'    🎯 相关度: {score:.4f}' if isinstance(score, (int, float)) else f'    🎯 相关度: {score}')
        print(f'    📄 文档ID: {file_id}')
        print(f'    📝 内容: {text_content}...')

except Exception as e:
    print(f'❌ 搜索结果解析失败: {e}')
    print('原始响应:', str(data) if 'data' in locals() else 'N/A')
"

    # 只测试第一个查询，避免输出过长
    break
done

echo
echo "✅ 测试完成！"
echo
echo "💡 提示："
echo "   - API 文档: http://localhost:8080/docs"
echo "   - 健康检查: http://localhost:8080/api/v1/health"