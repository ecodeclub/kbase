# KBase RAG - 极简RAG知识库系统

基于 Elasticsearch 9.x 的轻量级 RAG（检索增强生成）系统，支持多格式文档上传、腾讯云COS集成、文本分片、向量化和混合语义搜索。

## ✨ 特性

- 📄 **多格式文档解析** - 支持PDF、Markdown、TXT文件上传和文本提取
- 🔍 **混合搜索** - 结合文本匹配和向量语义搜索，支持权重配置
- ☁️ **云存储集成** - 支持腾讯云COS直接URL上传
- ⚡ **高性能** - 基于 Elasticsearch 9.x，支持大规模文档检索
- 🐍 **现代Python** - 使用 FastAPI、Pydantic、类型注解等现代工具
- 🔧 **企业级质量** - 完整的类型检查、代码规范、测试覆盖
- 🛡️ **权限处理** - 优雅处理COS权限限制，确保系统稳定运行

## 🚀 快速开始

### 环境要求

- **Python**: 3.13
- **uv**: 现代Python包管理器（强烈推荐）
- **Elasticsearch**: 9.x（用于文档存储和搜索）

### 1. 安装 uv

**macOS/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc  # 或重新打开终端
```

**Windows:**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**验证安装:**
```bash
uv --version
```

### 2. 项目设置

```bash
# 克隆项目
git clone <your-repo>
cd kbase

# 一键设置开发环境
make setup
```

`make setup` 会自动：
- ✅ 创建 Python 3.13 虚拟环境
- ✅ 安装所有依赖（包括开发工具）
- ✅ 配置 Git 预提交钩子

### 3. 启动 Elasticsearch

**使用 Docker（推荐）:**
```bash
make e2e_down && make e2e_up
```

**验证 ES 运行:**
```bash
curl http://localhost:9200
```

### 4. 启动应用

```bash
# 激活环境（如果未激活）
source .venv/bin/activate

# 启动开发服务器
make run
```

应用将在 http://localhost:8080 启动

## 📋 开发命令

| 命令           | 描述              |
|--------------|-----------------|
| `make setup` | 🚀 一键设置完整开发环境   |
| `make check` | ✅ 运行所有代码质量检查    |
| `make test`  | 🧪 运行测试并生成覆盖率报告 |
| `make cov`   | 🧪 运行测试并打开覆盖率报告 |
| `make run`   | ▶️ 启动开发服务器      |
| `make fmt`   | 🎨 格式化代码        |
| `make lint`  | ✨ 检查代码并自动修复     |
| `make type`  | 🔍 类型检查         |
| `make audit` | 🛡️ 扫描安全漏洞      |
| `make clean` | 🧹 清理临时文件       |
| `make docker_build` | docker打包        |
| `make docker_run`   | 运行 docker 镜像    |

## 🔧 API 接口

### 快速测试脚本

使用项目内置的测试脚本快速验证功能：
```bash
./.script/test.sh
```

### 主要端点

| 端点                                  | 方法 | 描述             |
|-------------------------------------|------|----------------|
| `/`                                 | GET | API 根路径和信息     |
| `/api/v1/health`                    | GET | 健康检查           |
| `/api/v1/documents/upload-file`     | POST | 本地文件上传         |
| `/api/v1/documents/upload-from-url` | POST | 从COS URL上传     |
| `/api/v1/documents/save`            | POST | 以JSON格式字符串上传文档 |
| `/api/v1/search`                    | POST | 文档搜索           |
| `/api/v1/tasks/{task_id}`           | GET | 查询任务状态         |

### 健康检查
```bash
curl http://localhost:8080/api/v1/health
```

### 文档上传
```bash
# 本地文件上传
curl -X POST "http://localhost:8080/api/v1/documents/upload-file" \
  -F "file=@document.pdf" \
  -F "category=技术文档" \
  -F "tags=AI,机器学习"

# COS URL上传
curl -X POST "http://localhost:8080/api/v1/documents/upload-from-url" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-cos-url/document.pdf"}'
```

### 搜索文档
```bash
curl -X POST "http://localhost:8080/api/v1/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "机器学习算法", "top_k": 5}'
```

## 🏗️ 架构说明

```
┌─────────────┐    ┌──────────────┐    ┌─────────────────┐
│  Web Layer  │───▶│ Service Layer│───▶│  Domain Layer   │
│   FastAPI   │    │   Service    │    │ Document/Search │
└─────────────┘    └──────────────┘    └─────────────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │  Elasticsearch  │
                   │     9.x         │
                   └─────────────────┘
```

- **Web Layer**: FastAPI 路由和请求处理
- **Service Layer**: 业务逻辑，文档处理和搜索
- **Domain Layer**: 领域模型和实体定义
- **Storage**: Elasticsearch 存储和检索

## 🧪 测试

```bash
# 运行所有测试
make test

# 运行特定测试文件
uv run pytest tests/test_api.py -v

# 运行特定测试用例
uv run pytest tests/test_api.py::TestAPI::test_health_check_endpoint -v

# 运行带输出的测试（用于调试）
uv run pytest tests/test_api.py -v -s

# 查看测试覆盖率报告
open htmlcov/index.html
```

### 测试类型

- **单元测试**: API端点功能测试
- **集成测试**: 文档上传和搜索流程测试  
- **性能测试**: 上传性能监控
- **边界测试**: 搜索鲁棒性验证

## 📝 代码质量

本项目使用企业级代码质量标准：

- **格式化**: Ruff (替代 Black)
- **Linting**: Ruff (替代 Flake8 + 多种插件)  
- **类型检查**: MyPy (strict 模式)
- **测试**: Pytest + 覆盖率报告
- **安全检查**: pip-audit
- **预提交钩子**: 自动代码检查

## 🤝 开发流程

1. **代码修改后运行检查:**
   ```bash
   make check  # 格式化 + lint + 类型检查
   ```

2. **提交代码:**
   ```bash
   git add .
   git commit -m "feat: 添加新功能"  
   # 自动触发预提交钩子检查
   ```

3. **推送代码:**
   ```bash
   git push
   # 自动触发测试和安全检查
   ```

## 🔧 配置

### 主配置文件

项目配置在 [`config.yaml`](./config.yaml)，包含以下主要配置：

- **Elasticsearch**: 连接URL、索引名称、超时设置
- **嵌入模型**: text2vec-base-chinese，768维向量
- **重排模型**: BGE-reranker-base
- **文档处理**: 分片大小、重叠设置
- **上传限制**: 最大50MB，支持 `.pdf` `.md` `.txt`
- **检索配置**: 向量和文本搜索权重可调

### 环境变量配置

腾讯云COS配置通过环境变量设置（创建 `.env` 文件）：

```bash
# 腾讯云COS配置
TENCENT_OSS__SECRET_ID=your_secret_id
TENCENT_OSS__SECRET_KEY=your_secret_key
TENCENT_OSS__BUCKET=your_bucket_name
TENCENT_OSS__REGION=your_region
```

### 测试配置

测试环境配置在 [`tests/fixtures/config.yaml`](./tests/fixtures/config.yaml)

## 🆘 故障排除

### Q: uv 命令不存在
**A**: 请按照上面的安装步骤安装 uv，并确保重新加载终端环境。

### Q: Elasticsearch 连接失败  
**A**: 确保 ES 服务运行在 localhost:9200，检查 `config.yaml` 配置。

### Q: COS上传功能不可用
**A**: 检查 `.env` 文件中的腾讯云COS配置：
```bash
# 确保配置了正确的COS环境变量
TENCENT_OSS__SECRET_ID=your_secret_id
TENCENT_OSS__SECRET_KEY=your_secret_key
TENCENT_OSS__BUCKET=your_bucket_name
TENCENT_OSS__REGION=your_region
```

### Q: COS权限不足错误
**A**: 系统已优雅处理权限限制：
- 应用启动时会跳过COS连接验证
- 元数据获取失败时会优雅降级
- 确保COS密钥至少有 `put_object` 和 `get_object` 权限

### Q: 测试失败
**A**: 确保 ES 服务正常运行，所有依赖已安装：
```bash
make setup  # 重新设置环境
```

### Q: 代码检查失败
**A**: 运行自动修复：
```bash
make check  # 自动格式化和修复大部分问题
```

---

💡 **提示**: 使用 `make help` 查看所有可用命令

## Docker 镜像和部署
Docker 打包的时候，忽略掉了很多文件，具体可以参考项目下的 .dockerignore 文件。

因此在使用 docker 来部署的时候，必须挂载：
- .env 文件
- config.yaml 文件

## 升级项目依赖

### 升级Python版本

1. 手动更新 pyproject.toml 配置文件中所有与 Python 版本相关的字段：

- 更新项目元数据 [project]:

```diff
- requires-python = ">=3.13"
+ requires-python = ">=3.14"
```

- 更新 Ruff 配置 [tool.ruff]:

```diff
- target-version = "py313"
+ target-version = "py314"
```

- 更新 MyPy 配置 [tool.mypy]:

```diff
- python_version = "3.13"
+ python_version = "3.14"
```

2. 使用 uv 重建虚拟环境


```bash
# 1. (推荐) 删除旧的虚拟环境，确保一个完全纯净的开始
rm -rf .venv

# 2. 使用 uv 创建一个指向 Python 3.14 的新虚拟环境
# uv 会自动在系统中寻找 3.14。如果找不到，它会下载一个！
uv venv --python 3.14

# 3. 激活新创建的环境
source .venv/bin/activate

# 4. 同步所有依赖到新环境
# uv sync 会读取 uv.lock 文件，在新环境中精确安装所有包
uv sync
```

### 升级其他依赖版本

> 使用 uv add 命令可以一站式完成版本更新、pyproject.toml 文件修改、锁文件更新和环境安装。

1. 检查所有过时的依赖名称:

```bash
uv pip list --outdated
```

2. 逐个升级`pyproject.toml`中定义的**直接**依赖，不要更新**间接依赖**:

```bash
uv add pydantic@latest
uv add langchain@latest
```

3. 升级后务必运行测试:

```bash
pytest
```