# Shared Directory Structure

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
