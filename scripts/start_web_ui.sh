#!/bin/bash
# QGIS Agent Web UI 启动脚本

set -e

echo "==================================="
echo "  QGIS Agent Web UI"
echo "==================================="
echo ""

# 检查是否在项目根目录
if [ ! -f "pyproject.toml" ]; then
    echo "错误: 请在项目根目录运行此脚本"
    exit 1
fi

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "警告: .env 文件不存在，从 .env.example 复制..."
    cp .env.example .env
    echo "请编辑 .env 文件配置环境变量"
    exit 1
fi

# 创建必要的目录
echo "创建必要的目录..."
mkdir -p uploads
mkdir -p ui/backend/frontend

# 检查数据库
echo "检查数据库连接..."
if ! docker ps | grep -q "qgis_postgres"; then
    echo "启动 PostgreSQL 数据库..."
    docker-compose up -d postgres
    echo "等待数据库启动..."
    sleep 5
fi

# 检查依赖
echo "检查 Python 依赖..."
if ! uv pip show fastapi > /dev/null 2>&1; then
    echo "安装 FastAPI 依赖..."
    uv pip install fastapi python-multipart
fi

# 启动服务
echo ""
echo "启动 Web UI 服务..."
echo "访问地址: http://localhost:9000"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

# 运行服务
cd ui/backend && python main.py
