# QGIS Agent Web UI - Vue 3 前端

基于 Vue 3 + Vite + Element Plus + Tailwind CSS 的现代化前端界面。

## 功能特性

✅ **所有原始 HTML 功能已完整实现**：
- 🌐 **实时聊天界面**: SSE 流式推送 Agent 执行状态
- 💬 **会话管理**: 多会话支持，创建、切换、删除会话
- 👤 **人工审核 (HITL)**: 在 Agent 执行关键步骤前进行人工审核
- 📁 **文件上传**: 支持拖拽和点击上传
- 📊 **节点监控**: 实时显示 Agent 当前执行的节点
- 💾 **历史记录**: 会话历史记录持久化
- 🖼️ **截图预览**: 右下角实时显示 QGIS 截图
- 🔌 **QGIS 插件监控**: 实时监控 QGIS MCP 插件状态（5秒轮询）
- ⚙️ **设置页面**: 配置 API 地址、模型参数、主题等

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue 3 | ^3.5.24 | 渐进式框架 |
| Vite | ^7.2.4 | 构建工具 |
| Element Plus | ^2.13.2 | UI 组件库 |
| Tailwind CSS | ^3.4.0 | 原子化 CSS |
| Pinia | ^3.0.4 | 状态管理 |
| Vue Router | ^5.0.2 | 路由管理 |
| Axios | ^1.13.4 | HTTP 客户端 |

## 开发指南

### 1. 安装依赖

```bash
cd ui/frontend
npm install
```

### 2. 启动开发服务器

```bash
npm run dev
```

前端将在 `http://localhost:5173` 启动，并自动代理 `/api` 请求到后端 `http://localhost:9000`。

### 3. 构建生产版本

```bash
npm run build
```

构建产物将输出到 `dist/` 目录。

## 部署架构

### 开发环境（前后端分离）

- 前端: `http://localhost:5173`
- 后端: `http://localhost:9000`
- Vite 自动代理 `/api` 和 `/shared` 请求

### 生产环境（简单部署）

将 `dist/` 目录内容复制到 FastAPI 后端的静态文件目录，或使用 Nginx 托管。

详细部署方式请参考项目主文档。
