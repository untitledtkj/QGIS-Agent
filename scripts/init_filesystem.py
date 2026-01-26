#!/usr/bin/env python3
"""
文件系统初始化脚本
创建shared目录结构
"""

import os
from pathlib import Path
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置
SHARED_ROOT_DIR = os.getenv("SHARED_ROOT_DIR", "./shared")

# 目录结构
DIRECTORIES = [
    "uploads",        # 上传文件
    "outputs",        # 输出文件
    "screenshots",    # 截图
    "logs",           # 日志
    "config",         # 配置
]


def create_directory_structure():
    """创建目录结构"""
    
    root = Path(SHARED_ROOT_DIR)
    
    # 创建根目录
    root.mkdir(parents=True, exist_ok=True)
    logger.info(f"✅ 创建根目录: {root.absolute()}")
    
    # 创建子目录
    for dir_name in DIRECTORIES:
        dir_path = root / dir_name
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"✅ 创建目录: {dir_path.absolute()}")
    
    # 创建.gitignore文件
    gitignore_path = root / ".gitignore"
    gitignore_content = """# 忽略上传的文件（示例数据）
uploads/*/original/*
uploads/*/processed/*

# 保留输出文件
!outputs/*/.gitkeep

# 忽略截图文件（可选，如果不想提交）
screenshots/*/*

# 忽略日志文件
logs/*.log

# 忽略临时文件
*.tmp
*.bak
"""
    gitignore_path.write_text(gitignore_content, encoding='utf-8')
    logger.info(f"✅ 创建.gitignore: {gitignore_path.absolute()}")
    
    # 创建.gitkeep文件（确保空目录被git跟踪）
    for dir_name in DIRECTORIES:
        dir_path = root / dir_name
        gitkeep_path = dir_path / ".gitkeep"
        gitkeep_path.touch()
        logger.info(f"✅ 创建.gitkeep: {gitkeep_path.absolute()}")
    
    # 创建README.md说明文件
    readme_path = root / "README.md"
    readme_content = """# Shared Directory Structure

此目录用于存储项目运行时的文件数据。

## 目录说明

- **uploads/**: 用户上传的文件（按session_id分组）
  - `{session_id}/original/`: 原始上传文件
  - `{session_id}/processed/`: 处理后的文件

- **outputs/**: 任务执行的输出文件（按session_id分组）
  - `{session_id}/`: 各会话的输出文件

- **screenshots/**: QGIS地图画布截图（按session_id分组）
  - `{session_id}/`: 各会话的截图文件

- **logs/**: 系统运行日志
  - `agent_{date}.log`: Agent运行日志
  - `mcp_{date}.log`: MCP Server日志

- **config/**: 配置文件
  - 运行时配置文件

## 注意事项

1. 所有会话数据都按`session_id`隔离存储
2. 日志文件按日期滚动
3. 上传文件会自动按日期清理（可配置）
4. 此目录不应被提交到Git（除.gitkeep文件）
"""
    readme_path.write_text(readme_content, encoding='utf-8')
    logger.info(f"✅ 创建README.md: {readme_path.absolute()}")
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ 文件系统初始化完成！")
    logger.info("=" * 60)
    logger.info(f"根目录: {root.absolute()}")
    logger.info(f"\n目录结构:")
    for dir_name in DIRECTORIES:
        logger.info(f"  - {dir_name}/")


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("开始初始化文件系统...")
    logger.info("=" * 60)
    create_directory_structure()
