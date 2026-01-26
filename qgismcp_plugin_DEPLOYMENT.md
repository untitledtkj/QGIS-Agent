# QGIS MCP HTTP 部署指南

## 快速开始

### 1. 启动QGIS插件服务器

在QGIS中启动MCP插件服务器（监听端口9876）：
- 菜单: `Plugins` > `QGIS MCP` > `QGIS MCP`
- 点击 "Start Server"

### 2. 安装依赖

```bash
cd /path/to/qgis_mcp
uv sync
```

### 3. 启动HTTP服务器

```bash
uv run python main_http.py
```

服务器将在 `http://0.0.0.0:8000` 上启动，提供以下端点：
- `GET /sse` - SSE事件流
- `POST /messages` - 消息发送端点

## 与Dify集成

### 配置MCP工具

1. 在Dify中，进入 **工具 > MCP工具**
2. 添加新的MCP服务器
3. 配置连接信息：
   - **名称**: QGIS MCP
   - **传输协议**: SSE (Server-Sent Events)
   - **服务器URL**: `http://localhost:8000`（如果Dify在不同机器，替换为实际IP）
   - **SSE端点**: `/sse`
   - **消息端点**: `/messages`

### 可用工具

连接成功后，Dify将可以访问以下QGIS工具：

- `ping` - 检查服务器连接
- `get_qgis_info` - 获取QGIS版本信息
- `load_project` - 加载QGIS项目
- `create_new_project` - 创建新项目
- `get_project_info` - 获取当前项目信息
- `add_vector_layer` - 添加矢量图层
- `add_raster_layer` - 添加栅格图层
- `get_layers` - 获取所有图层
- `remove_layer` - 删除图层
- `zoom_to_layer` - 缩放到图层
- `get_layer_features` - 获取图层要素
- `execute_processing` - 执行处理算法
- `save_project` - 保存项目
- `render_map` - 渲染地图为图片
- `execute_code` - 执行PyQGIS代码（谨慎使用）

## 测试HTTP服务器

运行测试脚本验证服务器是否正常工作：

```bash
# 安装测试依赖
uv sync --extra test

# 运行测试
uv run python test_http_server.py
```

## 部署到生产环境

### 使用Docker（推荐）

创建 `Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装uv
RUN pip install uv

# 复制项目文件
COPY . .

# 安装依赖
RUN uv sync

# 暴露端口
EXPOSE 8000

# 启动服务
CMD ["uv", "run", "python", "main_http.py"]
```

构建并运行：

```bash
docker build -t qgis-mcp-http .
docker run -p 8000:8000 -e QGIS_HOST=host.docker.internal qgis-mcp-http
```

### 使用systemd（Linux）

创建服务文件 `/etc/systemd/system/qgis-mcp-http.service`:

```ini
[Unit]
Description=QGIS MCP HTTP Server
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/qgis_mcp
ExecStart=/usr/bin/env uv run python main_http.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable qgis-mcp-http
sudo systemctl start qgis-mcp-http
```

### 配置反向代理（Nginx）

如果需要通过域名访问或添加SSL：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # SSE特定配置
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }
}
```

## 故障排除

### 1. 无法连接到QGIS

**错误**: `Could not connect to Qgis. Make sure the Qgis plugin is running.`

**解决方案**:
- 确保QGIS已启动
- 确保QGIS MCP插件已启用并点击了"Start Server"
- 检查防火墙是否阻止了端口9876

### 2. HTTP服务器无法启动

**错误**: `Address already in use`

**解决方案**:
```bash
# 查找占用8000端口的进程
netstat -ano | findstr :8000  # Windows
lsof -i :8000                 # Linux/Mac

# 终止进程或更改端口
# 编辑main_http.py, 修改port参数
```

### 3. Dify无法连接

**解决方案**:
- 确认HTTP服务器正在运行
- 检查URL是否正确（包括协议 http://）
- 如果Dify在Docker中，使用 `host.docker.internal` 而不是 `localhost`
- 检查网络策略和防火墙规则

## 安全建议

1. **生产环境**: 添加认证机制
2. **网络隔离**: 限制只有可信IP可以访问
3. **代码执行**: 谨慎使用 `execute_code` 工具
4. **日志监控**: 定期检查日志文件

## 性能优化

1. **连接池**: HTTP服务器已经使用持久连接到QGIS
2. **并发处理**: uvicorn默认支持异步处理
3. **资源限制**: 可以通过uvicorn参数限制工作进程数

```bash
uv run uvicorn main_http:app --host 0.0.0.0 --port 8000 --workers 4
```
