# 使用 bash 以支持更复杂的脚本
SHELL := /bin/bash

# Python 版本号
PYTHON_VERSION_TARGET := $(shell grep -E 'requires-python.*=' pyproject.toml | sed -E 's/.*">=([0-9]+\.[0-9]+).*/\1/')

# 默认目标: 显示帮助信息
.PHONY: help
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Commands:"
	@echo "  setup         🚀 一键设置完整的开发环境 (需要预先安装 uv)"
	@echo "  check         ✅ 运行所有代码质量检查 (格式化, lint, 类型检查)"
	@echo "  fmt           🎨 格式化代码"
	@echo "  lint          ✨ 检查代码并自动修复问题"
	@echo "  type          🔍 类型检查"
	@echo "  test          🧪 运行测试并生成覆盖率报告"
	@echo "  run           ▶️  启动开发服务器"
	@echo "  pre-commit    🔄 运行预提交检查"
	@echo "  audit         🛡️  扫描依赖中的安全漏洞"
	@echo "  e2e_up        🔄 启动集成测试环境"
	@echo "  e2e_down      🔄 关闭集成测试环境"
	@echo "  clean         🧹 清理临时文件和缓存"

# --- 主要的环境设置命令 ---

.PHONY: setup
setup: _check_uv _check_python
	@echo "📦 步骤 1/3: 正在使用 Python ${PYTHON_VERSION_TARGET} 创建虚拟环境 .venv..."
	@uv venv --clear -p ${PYTHON_VERSION_TARGET}
	@echo "✅ 虚拟环境创建成功。"
	@echo ""
	@echo "⛓️ 步骤 2/3: 正在根据 uv.lock 同步依赖..."
	@uv sync --frozen
	@echo "✅ 依赖安装完成。"
	@echo ""
	@echo "🪝 步骤 3/3: 正在安装 Git 提交/推送钩子..."
	@uv run pre-commit install
	@uv run pre-commit install -t pre-push
	@echo "✅ Git 钩子安装成功。"
	@echo ""
	@echo "🎉 全部设置完成！请运行 source .venv/bin/activate 激活环境。"

# --- 日常开发命令 ---

.PHONY: fmt
fmt:
	@uv run ruff format .

.PHONY: lint
lint:
	@uv run ruff check . --fix

.PHONY: type
type:
	@uv run mypy app tests

.PHONY: pre-commit
pre-commit:
	@uv run pre-commit run --all-files

.PHONY: check
check: fmt lint type

.PHONY: test
test:
	@uv run pytest -q --cov=app --cov-report=term-missing --cov-report=xml

.PHONY: audit
audit:
	@uv run pip-audit --strict

.PHONY: run
run:
	@uv run uvicorn app.main:app --host 0.0.0.0 --port 8080

.PHONY: e2e_up
e2e_up:
	docker compose -p kbase -f .script/integration_test_compose.yml up -d

.PHONY: e2e_down
e2e_down:
	docker compose -p kbase -f .script/integration_test_compose.yml down -v

.PHONY: clean
clean:
	@uv run pyclean .

# --- 内部帮助目标 ---

.PHONY: _check_uv
_check_uv:
	@if ! command -v uv &> /dev/null; then \
		echo "❌ 'uv' 命令未找到。"; \
		echo "请先安装 uv 包管理器："; \
		echo "详细安装说明请查看: README.md"; \
		exit 1; \
	fi

.PHONY: _check_python
_check_python:
	@if [ -z "${PYTHON_VERSION_TARGET}" ]; then \
        echo "❌ 错误: 无法从 pyproject.toml 中解析 'requires-python' 版本。"; \
        exit 1; \
    fi
	@if ! uv python find ${PYTHON_VERSION_TARGET} &> /dev/null; then \
		echo "ℹ️ 未找到 Python ${PYTHON_VERSION_TARGET}。正在使用 uv 自动安装..."; \
		if ! uv python install ${PYTHON_VERSION_TARGET}; then \
			echo "❌ Python ${PYTHON_VERSION_TARGET} 安装失败。请检查网络或 uv 文档。"; \
			exit 1; \
		fi; \
		echo "✅ Python ${PYTHON_VERSION_TARGET} 安装成功。"; \
	fi