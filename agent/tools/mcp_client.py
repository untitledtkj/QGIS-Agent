#!/usr/bin/env python3
"""
MCP客户端工具模块
提供与QGIS MCP Server的通信功能
"""

import os
import json
import logging
from typing import Dict, Any, Optional
import aiohttp
import asyncio
from dotenv import load_dotenv

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# QGIS MCP Server URL
QGIS_MCP_SERVER_URL = os.getenv("QGIS_MCP_SERVER_URL", "http://localhost:8000")


class QGISMCPClient:
    """QGIS MCP客户端"""
    
    def __init__(self, server_url: str = QGIS_MCP_SERVER_URL):
        """
        初始化MCP客户端
        
        Args:
            server_url: MCP服务器URL
        """
        self.server_url = server_url
        self.session_id: Optional[str] = None
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.sse_task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self.disconnect()
    
    async def connect(self) -> bool:
        """
        建立SSE连接
        
        Returns:
            是否连接成功
        """
        try:
            # 创建HTTP会话，增加max_line_size和max_field_size限制
            timeout = aiohttp.ClientTimeout(total=300)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(limit=100),
                # 增加chunk大小限制
                read_bufsize=2**20  # 1MB
            )
            
            # 启动SSE连接任务
            self.sse_task = asyncio.create_task(self._sse_listener())
            
            # 等待获取session_id（最多等待5秒）
            for _ in range(50):
                await asyncio.sleep(0.1)
                if self.session_id:
                    logger.info(f"MCP客户端连接成功: session_id={self.session_id}")
                    return True
            
            logger.error("未能获取session_id")
            return False
            
        except Exception as e:
            logger.error(f"MCP客户端连接失败: {e}")
            return False
    
    async def disconnect(self):
        """断开连接"""
        try:
            if self.sse_task:
                self.sse_task.cancel()
                try:
                    await self.sse_task
                except asyncio.CancelledError:
                    pass
            
            if self._session:
                await self._session.close()
            
            logger.info("MCP客户端已断开连接")
        except Exception as e:
            logger.error(f"断开连接时出错: {e}")
    
    async def _sse_listener(self):
        """SSE事件监听器"""
        url = f"{self.server_url}/sse"
        event_type = None
        
        try:
            async with self._session.get(url) as response:
                if response.status != 200:
                    logger.error(f"SSE连接失败: HTTP {response.status}")
                    return
                
                buffer = b''
                async for chunk in response.content.iter_any():
                    buffer += chunk
                    
                    # 尝试按行处理
                    while b'\n' in buffer:
                        line_bytes, buffer = buffer.split(b'\n', 1)
                        line_str = line_bytes.decode('utf-8', errors='ignore').strip()
                        
                        if not line_str:
                            continue
                        
                        if line_str.startswith("event:"):
                            event_type = line_str[6:].strip()
                        elif line_str.startswith("data:"):
                            data_str = line_str[5:].strip()
                            
                            # 处理endpoint事件（获取session_id）
                            if event_type == "endpoint":
                                self.session_id = data_str.split("=")[1]
                                logger.debug(f"获取session_id: {self.session_id}")
                            
                            # 处理message事件
                            elif event_type == "message":
                                try:
                                    data = json.loads(data_str)
                                    await self.message_queue.put(data)
                                except json.JSONDecodeError as e:
                                    # 数据可能太长，记录长度
                                    logger.warning(f"无法解析消息 (长度={len(data_str)}): {str(e)[:100]}")
        
        
        except asyncio.CancelledError:
            logger.debug("SSE监听器已取消")
        except Exception as e:
            logger.error(f"SSE监听器错误: {e}")
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: int = 60
    ) -> Dict[str, Any]:
        """
        调用MCP工具
        
        Args:
            tool_name: 工具名称
            arguments: 工具参数
            timeout: 超时时间（秒）
            
        Returns:
            工具执行结果
        """
        if not self.session_id:
            raise Exception("未建立MCP连接")
        
        url = f"{self.server_url}/messages?sessionId={self.session_id}"
        
        # 构建JSON-RPC请求
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        try:
            # 发送请求
            async with self._session.post(url, json=request) as response:
                if response.status != 202:
                    error_text = await response.text()
                    raise Exception(f"工具调用失败: HTTP {response.status}, {error_text}")
            
            # 等待响应
            result = await asyncio.wait_for(
                self.message_queue.get(),
                timeout=timeout
            )
            
            logger.debug(f"工具 '{tool_name}' 执行完成")
            return result
            
        except asyncio.TimeoutError:
            raise Exception(f"工具 '{tool_name}' 执行超时 ({timeout}秒)")
        except Exception as e:
            logger.error(f"调用工具 '{tool_name}' 失败: {e}")
            raise
    
    async def execute_code(self, code: str, timeout: int = 120) -> Dict[str, Any]:
        """
        执行PyQGIS代码
        
        Args:
            code: Python代码
            timeout: 超时时间（秒）
            
        Returns:
            执行结果
        """
        return await self.call_tool("execute_code", {"code": code}, timeout=timeout)
    
    async def capture_screenshot(
        self,
        path: str,
        width: int = 800,
        height: int = 600,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        捕获地图画布截图
        
        Args:
            path: 保存路径
            width: 图片宽度
            height: 图片高度
            timeout: 超时时间（秒）
            
        Returns:
            截图结果
        """
        return await self.call_tool(
            "capture_map_canvas",
            {"path": path, "width": width, "height": height},
            timeout=timeout
        )
    
    async def get_qgis_info(self, timeout: int = 10) -> Dict[str, Any]:
        """
        获取QGIS信息
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            QGIS信息
        """
        return await self.call_tool("get_qgis_info", {}, timeout=timeout)
    
    async def load_project(self, path: str, timeout: int = 30) -> Dict[str, Any]:
        """
        加载QGIS项目
        
        Args:
            path: 项目文件路径
            timeout: 超时时间（秒）
            
        Returns:
            加载结果
        """
        return await self.call_tool("load_project", {"path": path}, timeout=timeout)
    
    async def create_new_project(self, path: str, timeout: int = 30) -> Dict[str, Any]:
        """
        创建新项目并保存
        
        Args:
            path: 项目保存路径
            timeout: 超时时间（秒）
            
        Returns:
            创建结果
        """
        return await self.call_tool("create_new_project", {"path": path}, timeout=timeout)
    
    async def get_project_info(self, timeout: int = 10) -> Dict[str, Any]:
        """
        获取当前项目信息
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            项目信息
        """
        return await self.call_tool("get_project_info", {}, timeout=timeout)
    
    async def add_vector_layer(
        self,
        path: str,
        provider: str = "ogr",
        name: Optional[str] = None,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        添加矢量图层
        
        Args:
            path: 图层文件路径
            provider: 数据提供者（默认ogr）
            name: 图层名称（可选）
            timeout: 超时时间（秒）
            
        Returns:
            添加结果
        """
        params = {"path": path, "provider": provider}
        if name:
            params["name"] = name
        return await self.call_tool("add_vector_layer", params, timeout=timeout)
    
    async def add_raster_layer(
        self,
        path: str,
        provider: str = "gdal",
        name: Optional[str] = None,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        添加栅格图层
        
        Args:
            path: 图层文件路径
            provider: 数据提供者（默认gdal）
            name: 图层名称（可选）
            timeout: 超时时间（秒）
            
        Returns:
            添加结果
        """
        params = {"path": path, "provider": provider}
        if name:
            params["name"] = name
        return await self.call_tool("add_raster_layer", params, timeout=timeout)
    
    async def get_layers(self, timeout: int = 10) -> Dict[str, Any]:
        """
        获取所有图层列表
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            图层列表
        """
        return await self.call_tool("get_layers", {}, timeout=timeout)
    
    async def remove_layer(self, layer_id: str, timeout: int = 10) -> Dict[str, Any]:
        """
        移除指定图层
        
        Args:
            layer_id: 图层ID
            timeout: 超时时间（秒）
            
        Returns:
            移除结果
        """
        return await self.call_tool("remove_layer", {"layer_id": layer_id}, timeout=timeout)
    
    async def zoom_to_layer(self, layer_id: str, timeout: int = 10) -> Dict[str, Any]:
        """
        缩放到指定图层范围
        
        Args:
            layer_id: 图层ID
            timeout: 超时时间（秒）
            
        Returns:
            缩放结果
        """
        return await self.call_tool("zoom_to_layer", {"layer_id": layer_id}, timeout=timeout)
    
    async def get_layer_features(
        self,
        layer_id: str,
        limit: int = 10,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        获取图层要素
        
        Args:
            layer_id: 图层ID
            limit: 返回要素数量限制
            timeout: 超时时间（秒）
            
        Returns:
            要素列表
        """
        return await self.call_tool(
            "get_layer_features",
            {"layer_id": layer_id, "limit": limit},
            timeout=timeout
        )
    
    async def execute_processing(
        self,
        algorithm: str,
        parameters: Dict[str, Any],
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        执行QGIS处理算法
        
        Args:
            algorithm: 算法名称
            parameters: 算法参数
            timeout: 超时时间（秒），处理算法可能耗时较长
            
        Returns:
            执行结果
        """
        return await self.call_tool(
            "execute_processing",
            {"algorithm": algorithm, "parameters": parameters},
            timeout=timeout
        )
    
    async def save_project(self, path: Optional[str] = None, timeout: int = 30) -> Dict[str, Any]:
        """
        保存项目
        
        Args:
            path: 保存路径（可选，默认保存到当前项目路径）
            timeout: 超时时间（秒）
            
        Returns:
            保存结果
        """
        params = {}
        if path:
            params["path"] = path
        return await self.call_tool("save_project", params, timeout=timeout)
    
    async def render_map(
        self,
        path: str,
        width: int = 800,
        height: int = 600,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        渲染地图到图片文件
        
        Args:
            path: 保存路径
            width: 图片宽度
            height: 图片高度
            timeout: 超时时间（秒）
            
        Returns:
            渲染结果
        """
        return await self.call_tool(
            "render_map",
            {"path": path, "width": width, "height": height},
            timeout=timeout
        )
    
    async def inspect_qgis_env(self, timeout: int = 10) -> Dict[str, Any]:
        """
        检查QGIS环境状态（组合工具）
        获取项目信息和图层列表
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            环境信息（包含项目信息和图层列表）
        """
        try:
            # 并行获取项目信息和图层列表
            project_info = await self.get_project_info(timeout=timeout)
            layers_info = await self.get_layers(timeout=timeout)
            
            return {
                "success": True,
                "project": project_info,
                "layers": layers_info,
                "message": "环境检查完成"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "环境检查失败"
            }


# 全局MCP客户端实例
_mcp_client: Optional[QGISMCPClient] = None
_client_lock = asyncio.Lock()


async def get_mcp_client() -> QGISMCPClient:
    """
    获取全局MCP客户端实例（单例模式）
    
    Returns:
        MCP客户端实例
    """
    global _mcp_client
    
    async with _client_lock:
        # 检查是否需要重新创建客户端
        need_reconnect = False
        
        if _mcp_client is None:
            need_reconnect = True
        else:
            # 检查事件循环是否已关闭
            try:
                if _mcp_client._session and _mcp_client._session.closed:
                    need_reconnect = True
                    logger.info("MCP客户端会话已关闭，需要重新连接")
                # 检查事件循环
                elif _mcp_client.sse_task and _mcp_client.sse_task.done():
                    need_reconnect = True
                    logger.info("MCP客户端SSE任务已结束，需要重新连接")
            except Exception as e:
                logger.warning(f"检查MCP客户端状态失败: {e}，尝试重新连接")
                need_reconnect = True
        
        if need_reconnect:
            # 先清理旧连接
            if _mcp_client is not None:
                try:
                    await _mcp_client.disconnect()
                except:
                    pass
            
            # 创建新连接
            _mcp_client = QGISMCPClient()
            await _mcp_client.connect()
            if not _mcp_client.session_id:
                raise Exception("无法连接到QGIS MCP Server")
        
        return _mcp_client


async def close_mcp_client():
    """关闭全局MCP客户端"""
    global _mcp_client
    
    async with _client_lock:
        if _mcp_client:
            await _mcp_client.disconnect()
            _mcp_client = None


async def reset_mcp_client():
    """
    强制重置MCP客户端（用于事件循环切换时）
    """
    global _mcp_client
    
    async with _client_lock:
        if _mcp_client:
            try:
                await _mcp_client.disconnect()
            except Exception as e:
                logger.warning(f"关闭旧客户端时出错: {e}")
            _mcp_client = None
        
        logger.info("MCP客户端已重置")
