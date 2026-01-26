#!/usr/bin/env python3
"""
快速开始脚本
初始化项目环境和依赖
"""

import os
import subprocess
import sys
from pathlib import Path

def run_command(cmd, description):
    """运行命令并处理错误"""
    print(f"\n{'='*60}")
    print(f"🔄 {description}")
    print(f"{'='*60}")

    result = subprocess.run(cmd, shell=True)

    if result.returncode != 0:
        print(f"❌ {description} 失败")
        return False

    print(f"✅ {description} 成功")
    return True


def main():
    """主函数"""

    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║           QGIS Agent - 快速开始脚本                         ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    # 步骤1: 检查Python版本
    python_version = sys.version_info
    if python_version.major < 3 or (python_version.major == 3 and python_version.minor < 12):
        print("❌ Python版本要求: >= 3.12")
        print(f"当前版本: {python_version.major}.{python_version.minor}.{python_version.micro}")
        return

    print(f"✅ Python版本: {python_version.major}.{python_version.minor}.{python_version.micro}")

    # 步骤2: 检查uv是否安装
    if subprocess.run(["uv", "--version"], capture_output=True).returncode != 0:
        print("❌ uv未安装，请先安装uv")
        print("安装方法:")
        print("  Windows: powershell -ExecutionPolicy ByPass -c \"irm https://astral.sh/uv/install.ps1 | iex\"")
        print("  Mac: brew install uv")
        return

    print("✅ uv已安装")

    # 步骤3: 同步依赖
    if not run_command("uv sync", "同步项目依赖"):
        return

    # 步骤4: 检查Docker是否安装
    if subprocess.run(["docker", "--version"], capture_output=True).returncode != 0:
        print("❌ Docker未安装，请先安装Docker和Docker Compose")
        print("安装方法: https://docs.docker.com/get-docker/")
        return

    if subprocess.run(["docker-compose", "--version"], capture_output=True).returncode != 0:
        print("❌ Docker Compose未安装，请先安装Docker Compose")
        print("安装方法: https://docs.docker.com/compose/install/")
        return

    print("✅ Docker和Docker Compose已安装")

    # 步骤5: 检查.env文件
    env_file = Path(".env")
    env_example = Path(".env.example")

    if not env_file.exists() and env_example.exists():
        print("\n📋 创建.env文件...")
        import shutil
        shutil.copy(env_example, env_file)
        print("✅ 已创建.env文件，请根据实际情况修改配置")
        print("⚠️  重要: 请修改.env文件中的以下配置:")
        print("   - OPENAI_API_KEY (OpenAI API密钥)")
        print("   - QGIS_MCP_SERVER_URL (QGIS MCP Server地址)")

    elif env_file.exists():
        print("✅ .env文件已存在")

    else:
        print("⚠️  .env.example文件不存在，请手动创建.env文件")

    # 步骤6: 初始化文件系统
    print("\n📂 初始化文件系统...")
    shared_dir = Path("shared")
    shared_dir.mkdir(parents=True, exist_ok=True)

    for subdir in ["uploads", "outputs", "screenshots", "logs", "config"]:
        (shared_dir / subdir).mkdir(exist_ok=True)
        print(f"  ✅ {shared_dir/subdir}/")

    # 步骤7: 显示后续步骤
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                    ✅ 初始化完成！                          ║
    ╚═══════════════════════════════════════════════════════════╝

    📋 后续步骤:

    1. 配置环境变量
       修改 .env 文件，填写正确的配置信息（OPENAI_API_KEY等）

    2. 启动PostgreSQL（Docker）
       运行: docker-compose up -d

    3. 初始化数据库表
       运行: uv run python scripts/setup_database.py

    4. 启动服务

       a. 启动QGIS MCP插件
          - 打开QGIS
          - 菜单: 插件 > QGIS MCP > QGIS MCP
          - 点击 "Start Server"

       b. 启动统一MCP Server
          运行: uv run python mcp_server.py

    5. 测试MCP通信
       运行: uv run python scripts/test_mcp.py

    6. 开始实施Agent核心功能
       参考IMPLEMENTATION_GUIDE.md 阶段3-6

    📚 相关文档:
    - IMPLEMENTATION_GUIDE.md - 详细实施指南
    - doc/PRD.md - 产品需求文档
    - doc/技术文档.md - 技术设计文档

    🚀 祝项目顺利！
    """)


if __name__ == "__main__":
    main()
