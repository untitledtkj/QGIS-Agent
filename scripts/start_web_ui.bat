@echo off
REM QGIS Agent Web UI 启动脚本 (Windows)

echo ===================================
echo   QGIS Agent Web UI
echo ===================================
echo.

REM 检查是否在项目根目录
if not exist "pyproject.toml" (
    echo 错误: 请在项目根目录运行此脚本
    exit /b 1
)

REM 检查 .env 文件
if not exist ".env" (
    echo 警告: .env 文件不存在，从 .env.example 复制...
    copy .env.example .env
    echo 请编辑 .env 文件配置环境变量
    exit /b 1
)

REM 创建必要的目录
echo 创建必要的目录...
if not exist "uploads" mkdir uploads
if not exist "ui\backend\frontend" mkdir ui\backend\frontend

REM 检查数据库
echo 检查数据库连接...
docker ps | findstr "qgis_postgres" >nul
if errorlevel 1 (
    echo 启动 PostgreSQL 数据库...
    docker-compose up -d postgres
    echo 等待数据库启动...
    timeout /t 5 /nobreak >nul
)

REM 检查依赖
echo 检查 Python 依赖...
uv pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo 安装 FastAPI 依赖...
    uv pip install fastapi python-multipart
)

REM 启动服务
echo.
echo 启动 Web UI 服务...
echo 访问地址: http://localhost:9000
echo.
echo 按 Ctrl+C 停止服务
echo.

REM 运行服务
cd ui\backend
python main.py
