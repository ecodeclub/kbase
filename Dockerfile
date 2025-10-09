# 使用官方 Python 镜像
FROM python:3.13-slim

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 安装 uv（高性能依赖管理器）
RUN pip install --no-cache-dir uv

# 设置工作目录
WORKDIR /app

# 先复制依赖文件（利用缓存）
COPY pyproject.toml uv.lock ./

# 安装依赖到虚拟环境
RUN uv sync --frozen --no-cache --no-install-project

# 再复制源码
COPY . .

# 安装项目本身（可选，如果 pyproject.toml 里定义了 [project]）
RUN uv sync --frozen --no-cache

# 暴露端口（如果是 web 服务，比如 FastAPI/Flask）
EXPOSE 8000

# 启动命令（根据实际情况修改）
# 如果是 Web 服务
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

# 如果是 CLI 程序
# CMD ["uv", "run", "python", "kbase/main.py"]
