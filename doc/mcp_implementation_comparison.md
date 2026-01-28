# MCP Client 和 Executor 实现对比分析报告

## 概述

本报告对比分析当前项目（qgis-agentv2）中的 MCP client 和 executor 实现与 langchain 官方推荐方式的差异。

---

## 一、项目架构概览

### 1.1 当前项目架构

```
┌─────────────────────────────────────────────────────────────┐
│                    LangGraph Agent                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │          Executor Node (agent/nodes/executor.py)   │   │
│  │  - 构建工具列表                                   │   │
│  │  - 调用 LLM 决策工具使用                           │   │
│  │  - 执行工具调用                                    │   │
│  │  - 错误处理和重试                                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                         │                               │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │     MCP Client (agent/tools/mcp_client.py)        │   │
│  │  - QGISMCPClient 类                               │   │
│  │  - SSE 连接管理                                   │   │
│  │  - 工具转换 (MCP → LangChain)                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────┘
                          │ SSE
                          ▼
┌─────────────────────────────────────────────────────────────┐
│     Unified MCP Server (mcp_server.py)                   │
│  - Starlette HTTP 服务                                   │
│  - SSE 端点 (/sse)                                     │
│  - JSON-RPC 消息处理                                    │
│  - 会话管理                                             │
└─────────────────────────┬───────────────────────────────┘
                          │ Socket
                          ▼
┌─────────────────────────────────────────────────────────────┐
│   FastMCP Server (src/qgis_mcp/qgis_mcp_server.py)      │
│  - FastMCP 框架                                          │
│  - QGIS 工具封装                                        │
│  - Socket 通信层                                         │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│          QGIS MCP Plugin (in QGIS process)               │
│  - PyQGIS 执行环境                                       │
│  - 实际工具实现                                          │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 LangChain 官方推荐架构

```
┌─────────────────────────────────────────────────────────────┐
│                  LangChain Agent                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │          createAgent()                            │   │
│  │  - 自动工具选择                                    │   │
│  │  - 工具执行                                        │   │
│  └─────────────────────────────────────────────────────┘   │
│                         │                               │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  MultiServerMCPClient                            │   │
│  │  - getTools() 直接返回 LangChain 工具              │   │
│  │  - 无状态会话管理（默认）                          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────┘
                          │ stdio / SSE / HTTP
                          ▼
┌─────────────────────────────────────────────────────────────┐
│         MCP Server (@modelcontextprotocol/sdk)            │
│  - 纯 MCP 服务器                                        │
│  - 工具定义和实现                                       │
│  - 标准传输协议                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、详细对比分析

### 2.1 MCP Client 实现

#### 项目实现：`agent/tools/mcp_client.py`

**特点：**
- **完全自定义实现**：从头编写 `QGISMCPClient` 类
- **持久化连接**：使用全局单例模式，保持长连接
- **手动 SSE 实现**：自定义 SSE 监听器和消息队列
- **复杂状态管理**：
  - session_id 管理
  - 请求/响应匹配
  - 消息队列和 pending 列表
  - 连接健康检查

**核心代码片段：**

```python
class QGISMCPClient:
    def __init__(self, server_url: str = QGIS_MCP_SERVER_URL):
        self.server_url = server_url
        self.session_id: Optional[str] = None
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.sse_task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._request_id: int = 0
        self._request_lock = asyncio.Lock()
        self._pending_messages: List[Dict[str, Any]] = []
        self._messages_endpoint: Optional[str] = None
        self._initialized: bool = False

    async def connect(self) -> bool:
        # 创建 HTTP 会话
        self._session = aiohttp.ClientSession(
            timeout=timeout,
            connector=aiohttp.TCPConnector(limit=100),
            read_bufsize=2**20  # 1MB
        )

        # 启动 SSE 连接任务
        self.sse_task = asyncio.create_task(self._sse_listener())

        # 等待获取 session_id
        for _ in range(50):
            await asyncio.sleep(0.1)
            if self.session_id:
                await self._initialize_session()
                return True
```

**优点：**
- 精细控制连接生命周期
- 支持会话持久化
- 自定义错误处理和重试逻辑
- 支持复杂的请求匹配机制

**缺点：**
- 代码复杂度高（791 行）
- 维护成本高
- 潜在的资源泄漏风险（需要仔细管理任务、会话等）
- 不符合官方推荐的无状态模式

#### LangChain 官方实现

**特点：**
- **标准化实现**：使用 `@langchain/mcp-adapters` 库
- **无状态设计**：每次工具调用创建新会话（默认）
- **支持多服务器**：`MultiServerMCPClient` 可同时连接多个 MCP 服务器
- **简单易用**：几行代码即可完成集成

**核心代码片段：**

```typescript
import { MultiServerMCPClient } from "@langchain/mcp-adapters";

const client = new MultiServerMCPClient({
    math: {
        transport: "stdio",
        command: "node",
        args: ["/path/to/math_server.js"],
    },
    weather: {
        transport: "sse",
        url: "http://localhost:8000/mcp",
    },
});

const tools = await client.getTools();
```

**优点：**
- 代码简洁（几行配置）
- 官方维护，稳定可靠
- 无需手动管理连接状态
- 支持多服务器聚合
- 自动转换工具格式

**缺点：**
- 无状态设计可能不适合需要持久化会话的场景
- 自定义能力受限
- 仅支持标准传输协议

**差异总结：**

| 维度 | 项目实现 | 官方推荐 |
|------|---------|---------|
| 代码复杂度 | 791 行 | ~10 行 |
| 连接管理 | 持久化单例 + 手动状态 | 无状态（默认） |
| 会话管理 | 手动实现 session_id | 自动管理 |
| 工具获取 | 自定义转换逻辑 | `getTools()` 直接返回 |
| 多服务器支持 | 不支持 | 原生支持 |
| 状态保持 | 支持 | 需要显式配置 |

---

### 2.2 Executor 实现

#### 项目实现：`agent/nodes/executor_node.py`

**特点：**
- **基于 LangGraph 的自定义节点**：`executor_node(state)` 函数
- **多轮执行循环**：最多 8 轮 LLM 交互
- **工具构建流程**：`_build_mcp_tools()` 构建工具集
- **执行状态管理**：
  - 定期状态推送（每 5 秒）
  - 截图捕获机制
  - 执行日志保存
  - 错误重试（最多 3 次）
- **Runtime API RAG**：支持运行时补充 API 文档

**核心代码片段：**

```python
async def _executor_node_async(state: AgentState) -> Dict[str, Any]:
    # 获取当前步骤
    step = plan.steps[current_step_id]

    # 构建 Prompt 与工具集
    tools, tool_map, tool_catalog = await _build_mcp_tools(step_context)

    # 多轮执行
    max_action_rounds = 8
    for round_idx in range(max_action_rounds):
        response = tool_bound_llm.invoke(llm_messages)
        tool_calls = _extract_tool_calls(response)

        # 执行工具调用
        for call in tool_calls:
            tool_name = call.get("name")
            args = call.get("args")
            result = await tool.ainvoke(args)
            # ...处理结果
```

**优点：**
- 完全控制执行流程
- 精细的状态管理和错误处理
- 支持运行时文档补充
- 自定义状态推送和截图

**缺点：**
- 代码复杂（552 行）
- 需要手动管理工具列表
- 执行循环逻辑需要优化
- 与 LangGraph 生态集成度较低

#### LangChain 官方实现

**特点：**
- **标准 Agent**：使用 `createAgent()`
- **自动工具执行**：Agent 自动选择和执行工具
- **内置重试机制**：Agent 内置错误处理
- **简单配置**：一行代码创建 Agent

**核心代码片段：**

```typescript
const client = new MultiServerMCPClient({...});
const tools = await client.getTools();

const agent = createAgent({
    model: "claude-sonnet-4-5-20250929",
    tools,
});

const response = await agent.invoke({
    messages: [{ role: "user", content: "what's (3 + 5) x 12?" }],
});
```

**优点：**
- 极简代码（几行）
- 官方维护的 Agent 实现
- 自动工具选择和执行
- 内置错误处理和重试

**缺点：**
- 执行流程定制能力受限
- 状态推送等高级功能需要额外开发
- 与 LangGraph 深度集成不够

**差异总结：**

| 维度 | 项目实现 | 官方推荐 |
|------|---------|---------|
| 代码复杂度 | 552 行 | ~20 行 |
| 执行模型 | 多轮循环 + 手动管理 | Agent 自动执行 |
| 工具管理 | 手动构建和绑定 | 自动绑定 |
| 错误处理 | 手动实现（3 次重试） | 内置机制 |
| 状态推送 | 自定义实现（每 5 秒） | 不支持 |
| 截图功能 | 自定义实现 | 不支持 |
| Runtime RAG | 自定义实现 | 不支持 |

---

### 2.3 MCP Server 实现

#### 项目实现：`mcp_server.py`

**特点：**
- **双层架构**：HTTP Server + FastMCP
- **自定义 HTTP 接口**：
  - SSE 端点 (`/sse`)
  - 消息端点 (`/messages`)
  - JSON-RPC 协议处理
- **会话管理**：使用 `anyio` memory stream
- **工具聚合**：同时暴露 FastMCP 工具和 API 提取工具

**核心代码片段：**

```python
async def handle_sse(request: Request) -> EventSourceResponse:
    session_id = str(uuid.uuid4())

    async def event_generator():
        send_stream, receive_stream = anyio.create_memory_object_stream(100)
        sessions[session_id] = send_stream

        # Send endpoint event
        yield {"event": "endpoint", "data": f"/messages?sessionId={session_id}"}

        # Stream messages
        async for message in receive_stream:
            yield {"event": "message", "data": json.dumps(message)}

    return EventSourceResponse(event_generator())

async def handle_messages(request: Request) -> Response:
    session_id = request.query_params.get("sessionId")
    message_data = await request.json()
    method = message_data.get("method")

    # Process JSON-RPC methods
    if method == "tools/list":
        # ...聚合工具列表
    elif method == "tools/call":
        # ...调用工具
```

**优点：**
- 完整的 MCP HTTP/SSE 实现
- 支持多种工具源
- 自定义会话管理

**缺点：**
- 非标准 MCP 服务器（HTTP 桥接）
- 复杂的会话管理逻辑
- 可能与官方适配器不兼容

#### LangChain 官方实现

**特点：**
- **标准 MCP 服务器**：使用 `@modelcontextprotocol/sdk`
- **纯 MCP 协议**：不涉及 HTTP 桥接
- **简单工具定义**：使用 `@mcp.tool()` 装饰器

**核心代码片段：**

```typescript
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";

const server = new Server({
    name: "weather-server",
    version: "0.1.0",
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { location } = request.params.arguments;
    return {
        content: [{ type: "text", text: `It's always sunny in ${location}` }],
    };
});

app.post("/mcp", async (req, res) => {
    const transport = new SSEServerTransport("/mcp", res);
    await server.connect(transport);
});
```

**优点：**
- 标准化实现
- 简单直接
- 官方支持
- 易于集成

**缺点：**
- 工具定义相对简单
- 缺少高级功能（如多工具源聚合）

**差异总结：**

| 维度 | 项目实现 | 官方推荐 |
|------|---------|---------|
| 架构 | HTTP Server + FastMCP 双层 | 纯 MCP 服务器 |
| 协议 | HTTP + SSE + JSON-RPC | MCP 标准协议 |
| 工具源 | FastMCP + API 提取器 | 单一工具源 |
| 会话管理 | 自定义（anyio stream） | 传输层管理 |
| 代码复杂度 | 362 行 | ~100 行 |

---

### 2.4 传输协议

#### 项目实现

**SSE + HTTP 桥接：**
- 自定义 SSE 实现（`aiohttp`）
- HTTP POST 用于发送消息
- 自定义 JSON-RPC 封装

```python
# SSE 监听器
async def _sse_listener(self):
    url = f"{self.server_url}/sse"
    async with self._session.get(url) as response:
        async for chunk in response.content.iter_any():
            # 手动解析 SSE 事件
            if line_str.startswith("event:"):
                event_type = line_str[6:].strip()
            elif line_str.startswith("data:"):
                data_str = line_str[5:].strip()
                # 处理数据
```

#### LangChain 官方实现

**标准传输协议：**
- `stdio`：进程通信
- `sse`：Server-Sent Events
- `streamable-http`：HTTP 流式传输

```typescript
// stdio transport
const client = new MultiServerMCPClient({
    math: {
        transport: "stdio",
        command: "node",
        args: ["/path/to/math_server.js"],
    },
});

// SSE transport
const client = new MultiServerMCPClient({
    weather: {
        transport: "sse",
        url: "http://localhost:8000/mcp",
    },
});
```

**差异总结：**

| 维度 | 项目实现 | 官方推荐 |
|------|---------|---------|
| SSE | 自定义 aiohttp 实现 | 标准 SSEServerTransport |
| HTTP | 自定义 JSON-RPC 桥接 | 标准 streamable-http |
| stdio | 不支持 | 原生支持 |
| 协议适配度 | 部分兼容 | 完全兼容 |

---

## 三、关键差异总结

### 3.1 架构层面

| 方面 | 项目实现 | 官方推荐 | 差异程度 |
|------|---------|---------|---------|
| 整体架构 | 多层代理 + 自定义 MCP Client | 标准化 MCP Client + Agent | **大** |
| 连接管理 | 持久化单例 | 无状态（默认） | **大** |
| 会话处理 | 手动实现 | 自动管理 | **大** |
| 工具管理 | 手动转换 | 自动转换 | **中** |
| 执行模型 | LangGraph 节点 + 循环 | 标准 Agent | **大** |

### 3.2 代码层面

| 指标 | 项目实现 | 官方推荐 | 差异 |
|------|---------|---------|------|
| Client 代码行数 | 791 行 | ~10 行 | **79 倍** |
| Executor 代码行数 | 552 行 | ~20 行 | **27 倍** |
| Server 代码行数 | 362 行 | ~100 行 | **3.6 倍** |
| 总代码量 | ~1700 行 | ~130 行 | **13 倍** |

### 3.3 功能层面

| 功能 | 项目实现 | 官方推荐 | 备注 |
|------|---------|---------|------|
| 持久化会话 | ✅ 支持 | ⚠️ 需配置 | 项目优势 |
| 多服务器 | ❌ 不支持 | ✅ 支持 | 官方优势 |
| 状态推送 | ✅ 自定义 | ❌ 不支持 | 项目优势 |
| 截图功能 | ✅ 自定义 | ❌ 不支持 | 项目优势 |
| Runtime RAG | ✅ 自定义 | ❌ 不支持 | 项目优势 |
| 自动重试 | ✅ 手动实现 | ✅ 内置 | 官方更优 |
| 错误处理 | ✅ 精细控制 | ✅ 标准化 | 官方更易维护 |
| 类型安全 | ⚠️ 部分 | ✅ TypeScript | 官方优势 |

---

## 四、优缺点对比

### 4.1 项目实现

**优点：**
1. **精细控制**：对连接、会话、执行有完全控制权
2. **持久化会话**：支持跨工具调用的状态保持
3. **高级功能**：状态推送、截图、Runtime RAG 等
4. **适配 QGIS 特性**：针对 QGIS 场景深度优化

**缺点：**
1. **代码复杂度高**：约 1700 行 vs 官方 130 行（13 倍）
2. **维护成本高**：需要手动管理状态、连接、错误处理
3. **不符合官方规范**：自定义实现可能与未来标准不兼容
4. **功能重复造轮子**：很多功能官方已经实现
5. **潜在 Bug 风险**：复杂的状态管理容易引入 bug

### 4.2 官方推荐

**优点：**
1. **代码简洁**：约 130 行即可完成完整集成
2. **官方维护**：稳定、可靠、持续更新
3. **标准化**：符合 MCP 协议规范
4. **易于集成**：与 LangChain 生态无缝集成
5. **多服务器支持**：原生支持多 MCP 服务器聚合

**缺点：**
1. **定制化受限**：难以实现高级功能（状态推送等）
2. **无状态默认**：需要额外配置才能支持持久化会话
3. **场景适配**：可能需要额外开发以满足特定需求

---

## 五、兼容性分析

### 5.1 与 LangChain 生态的兼容性

| 组件 | 兼容性 | 说明 |
|------|--------|------|
| MCP Server | ⚠️ 部分兼容 | HTTP 桥接层可能与官方适配器不完全兼容 |
| MCP Client | ❌ 不兼容 | 自定义实现，无法使用官方适配器 |
| Executor | ✅ 兼容 | 基于 LangGraph，可以集成到 LangChain Agent |
| 工具转换 | ✅ 兼容 | 返回 `StructuredTool`，可以被 LangChain Agent 使用 |

### 5.2 与 MCP 协议的兼容性

| 协议特性 | 兼容性 | 说明 |
|---------|--------|------|
| JSON-RPC 2.0 | ✅ 兼容 | 实现了标准 JSON-RPC |
| 初始化握手 | ✅ 兼容 | 实现了 `initialize` 和 `notifications/initialized` |
| 工具列表 | ✅ 兼容 | 实现了 `tools/list` |
| 工具调用 | ✅ 兼容 | 实现了 `tools/call` |
| SSE 传输 | ⚠️ 部分兼容 | 自定义 SSE 实现，可能不兼容所有客户端 |
| stdio 传输 | ❌ 不支持 | 只支持 HTTP/SSE |

---

## 六、建议与改进方向

### 6.1 短期建议

1. **评估迁移成本**：
   - 分析当前高级功能（状态推送、截图、Runtime RAG）的必要性
   - 如果这些功能可以放弃，建议迁移到官方实现
   - 如果需要保留，考虑混合方案

2. **代码简化**：
   - 使用官方 `MultiServerMCPClient` 替换自定义 Client
   - 使用 `createAgent` 替换自定义 Executor（如果适用）
   - 简化 MCP Server 架构

3. **增强兼容性**：
   - 使用标准 `SSEServerTransport` 替换自定义 SSE 实现
   - 考虑添加 stdio 传输支持

### 6.2 中期建议

1. **功能分离**：
   - 将高级功能（状态推送、截图等）提取为独立模块
   - 核心 MCP 功能使用官方实现
   - 高级功能通过装饰器或中间件实现

2. **标准化架构**：
   ```
   标准层（官方实现）
     ├─ MCP Client (MultiServerMCPClient)
     ├─ MCP Server (@modelcontextprotocol/sdk)
     └─ Agent (createAgent)

   扩展层（自定义实现）
     ├─ 状态推送中间件
     ├─ 截图捕获器
     └─ Runtime RAG 模块
   ```

3. **迁移路径**：
   - Phase 1: 迁移 MCP Client 到官方实现
   - Phase 2: 迁移 MCP Server 到标准协议
   - Phase 3: 逐步迁移 Executor 到标准 Agent

### 6.3 长期建议

1. **参与社区**：
   - 将高级功能（如 Runtime RAG）贡献给官方库
   - 参与协议演进讨论

2. **建立最佳实践**：
   - 记录 QGIS 场景下的 MCP 使用模式
   - 发布示例和教程

3. **持续优化**：
   - 跟进官方更新
   - 定期评估迁移收益

---

## 七、结论

### 7.1 差异程度评估

**总体差异：较大（70%）**

| 维度 | 差异程度 | 权重 | 加权得分 |
|------|---------|------|---------|
| 架构设计 | 大 (0.8) | 30% | 0.24 |
| 代码实现 | 大 (0.9) | 40% | 0.36 |
| 协议兼容 | 中 (0.5) | 20% | 0.10 |
| 生态集成 | 小 (0.3) | 10% | 0.03 |
| **加权总分** | | **100%** | **0.73** |

**差异等级：较大（0.7 - 0.8）**

### 7.2 是否需要迁移？

**建议：有条件迁移**

**迁移条件：**
1. ✅ 状态推送、截图等高级功能可以接受降级或通过其他方式实现
2. ✅ 可以投入时间进行代码重构和测试
3. ✅ 团队愿意长期维护与官方生态的兼容性

**不迁移条件：**
1. ❌ 高级功能（状态推送、Runtime RAG）是核心需求
2. ❌ 项目稳定，不想承担重构风险
3. ❌ 团队资源有限，无法支持迁移

**混合方案推荐：**
- 核心 MCP 功能（Client、Server）使用官方实现
- 高级功能（状态推送、截图）通过中间件/插件实现
- Executor 可以逐步迁移，也可以保持现状

### 7.3 最终建议

**对于当前项目：**

1. **短期**：保持现状，评估迁移收益
2. **中期**：如果需要添加新功能或重构，考虑使用官方实现
3. **长期**：逐步迁移到官方架构，通过扩展层实现高级功能

**对于新项目：**
- **强烈建议**使用官方实现
- 通过扩展层实现定制化需求
- 遵循官方最佳实践

---

## 八、附录

### A. 关键代码对比

#### A.1 Client 初始化

**项目实现（791 行）：**
```python
# 完整代码见 agent/tools/mcp_client.py
class QGISMCPClient:
    def __init__(self, server_url: str = QGIS_MCP_SERVER_URL):
        # ...791 行复杂实现
```

**官方实现（~10 行）：**
```typescript
import { MultiServerMCPClient } from "@langchain/mcp-adapters";

const client = new MultiServerMCPClient({
    math: { transport: "stdio", command: "node", args: ["server.js"] },
    weather: { transport: "sse", url: "http://localhost:8000/mcp" },
});
```

#### A.2 工具获取和执行

**项目实现：**
```python
# 手动构建工具
mcp_client = await get_mcp_client()
tool_specs = await mcp_client.list_tools()
tools = await mcp_client.get_tools()

# 手动执行循环
for round_idx in range(max_action_rounds):
    response = tool_bound_llm.invoke(llm_messages)
    tool_calls = _extract_tool_calls(response)
    # ...552 行实现
```

**官方实现：**
```typescript
// 自动获取工具
const tools = await client.getTools();

// 创建 Agent 自动执行
const agent = createAgent({ model, tools });
const response = await agent.invoke({ messages });
```

### B. 参考资料

- [LangChain MCP 文档](https://docs.langchain.com/oss/javascript/langchain/mcp)
- [MCP 协议规范](https://modelcontextprotocol.io/introduction)
- [LangChain MCP Adapters](https://github.com/langchain-ai/langchainjs/tree/main/libs/langchain-mcp-adapters)
- [Model Context Protocol SDK](https://github.com/modelcontextprotocol/typescript-sdk)

---

**报告生成时间**：2026-01-28
**分析对象**：qgis-agentv2 项目 MCP 实现与 LangChain 官方推荐
**分析维度**：架构、代码、功能、兼容性、迁移成本
**总体结论**：差异较大（73%），建议有条件迁移或采用混合方案
