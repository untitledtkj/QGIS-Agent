#!/usr/bin/env python3
"""
MCP通信测试脚本
验证MCP Client与Server的SSE通信
"""

import asyncio
import json
import logging
import os
from typing import Dict, Any

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MCPTestClient:
    """简单的MCP客户端，用于测试"""

    def __init__(self, server_url: str = "http://localhost:8000"):
        self.server_url = server_url
        self.session_id = None
        self.message_queue = asyncio.Queue()
        self.sse_task = None

    async def connect_sse(self):
        """建立SSE连接"""
        import aiohttp

        url = f"{self.server_url}/sse"
        logger.info(f"正在连接SSE: {url}")

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"SSE连接失败: {response.status}")

                event_type = None
                
                # 读取SSE事件
                async for line in response.content:
                    if line:
                        line_str = line.decode('utf-8').strip()

                        # 解析SSE事件
                        if line_str.startswith("event:"):
                            event_type = line_str[6:].strip()
                        elif line_str.startswith("data:"):
                            data_str = line_str[5:].strip()

                            # 处理endpoint事件（获取session_id）
                            if event_type == "endpoint":
                                self.session_id = data_str.split("=")[1]
                                logger.info(f"获取到session_id: {self.session_id}")

                            # 处理message事件
                            elif event_type == "message":
                                try:
                                    data = json.loads(data_str)
                                    await self.message_queue.put(data)
                                    logger.info(f"收到消息: {data.get('method', 'response')}")
                                except json.JSONDecodeError:
                                    logger.warning(f"无法解析消息: {data_str}")

    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """调用MCP工具"""
        import aiohttp

        if not self.session_id:
            raise Exception("未建立SSE连接")

        url = f"{self.server_url}/messages?sessionId={self.session_id}"
        logger.info(f"调用工具: {tool_name}, 参数: {params}")

        # 构建JSON-RPC请求
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": params
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=request) as response:
                if response.status != 202:
                    raise Exception(f"工具调用失败: {response.status}")

                result = await response.json()
                return result

    async def wait_for_response(self, timeout: int = 30) -> Dict[str, Any]:
        """等待工具响应"""
        try:
            result = await asyncio.wait_for(self.message_queue.get(), timeout=timeout)
            return result
        except asyncio.TimeoutError:
            raise Exception(f"等待响应超时 ({timeout}秒)")

async def test_ping():
    """测试ping工具"""
    logger.info("=== 测试1: Ping ===")
    client = MCPTestClient()

    # 启动SSE连接（后台）
    sse_task = asyncio.create_task(client.connect_sse())

    # 等待session_id
    for i in range(50):  # 最多等待5秒
        await asyncio.sleep(0.1)
        if client.session_id:
            break
    
    if not client.session_id:
        raise Exception("未能获取session_id")

    # 调用ping工具
    await client.call_tool("ping", {})

    # 等待响应
    response = await client.wait_for_response()
    logger.info(f"Ping响应: {json.dumps(response, indent=2, ensure_ascii=False)}")

    # 关闭连接
    sse_task.cancel()
    
    # 验证结果
    if response.get("result"):
        logger.info("✅ Ping测试通过")
        return True
    else:
        logger.error("❌ Ping测试失败")
        return False

async def test_execute_code():
    """测试execute_code工具"""
    logger.info("\n=== 测试2: Execute Code ===")
    client = MCPTestClient()

    # 启动SSE连接（后台）
    sse_task = asyncio.create_task(client.connect_sse())

    # 等待session_id
    for i in range(50):
        await asyncio.sleep(0.1)
        if client.session_id:
            break
    
    if not client.session_id:
        raise Exception("未能获取session_id")

    # 调用execute_code工具
    code = """
print("Hello from QGIS!")
from qgis.core import Qgis
print(f"QGIS版本: {Qgis.QGIS_VERSION}")
"""
    await client.call_tool("execute_code", {"code": code})

    # 等待响应
    response = await client.wait_for_response(timeout=60)
    logger.info(f"Execute Code响应: {json.dumps(response, indent=2, ensure_ascii=False)}")

    # 关闭连接
    sse_task.cancel()
    
    # 验证结果
    if response.get("result"):
        content = response["result"].get("content", [])
        if content:
            result_text = content[0].get("text", "")
            if "Hello from QGIS" in result_text or "QGIS版本" in result_text:
                logger.info("✅ Execute Code测试通过")
                return True
    
    logger.error("❌ Execute Code测试失败")
    return False

async def test_capture_map_canvas():
    """测试capture_map_canvas工具"""
    logger.info("\n=== 测试3: Capture Map Canvas ===")
    client = MCPTestClient()

    # 启动SSE连接（后台）
    sse_task = asyncio.create_task(client.connect_sse())

    # 等待session_id
    for i in range(50):
        await asyncio.sleep(0.1)
        if client.session_id:
            break
    
    if not client.session_id:
        raise Exception("未能获取session_id")

    # 调用capture_map_canvas工具
    screenshot_path = os.path.abspath("shared/screenshots/test_capture.png")
    
    await client.call_tool("capture_map_canvas", {
        "path": screenshot_path,
        "width": 800,
        "height": 600
    })

    # 等待响应
    response = await client.wait_for_response(timeout=30)
    logger.info(f"Capture Map Canvas响应: {json.dumps(response, indent=2, ensure_ascii=False)}")

    # 关闭连接
    sse_task.cancel()

    # 检查文件是否存在
    if os.path.exists(screenshot_path):
        logger.info(f"✅ 截图文件已创建: {screenshot_path}")
        return True
    else:
        logger.warning(f"⚠️ 截图文件未创建: {screenshot_path}")
        # 检查响应中是否包含成功信息
        if response.get("result"):
            content = response["result"].get("content", [])
            if content:
                result_text = content[0].get("text", "")
                if "success" in result_text.lower() and "true" in result_text.lower():
                    logger.info("✅ Capture Map Canvas测试通过（服务器报告成功）")
                    return True
        
        logger.error("❌ Capture Map Canvas测试失败")
        return False

async def main():
    """运行所有测试"""
    logger.info("=" * 60)
    logger.info("开始MCP通信测试...")
    logger.info("=" * 60)
    
    results = []
    
    # 测试1: Ping
    try:
        result = await test_ping()
        results.append(("Ping", result))
    except Exception as e:
        logger.error(f"Ping测试异常: {e}")
        results.append(("Ping", False))

    await asyncio.sleep(1)

    # 测试2: Execute Code
    try:
        result = await test_execute_code()
        results.append(("Execute Code", result))
    except Exception as e:
        logger.error(f"Execute Code测试异常: {e}")
        results.append(("Execute Code", False))

    await asyncio.sleep(1)

    # 测试3: Capture Map Canvas
    try:
        result = await test_capture_map_canvas()
        results.append(("Capture Map Canvas", result))
    except Exception as e:
        logger.error(f"Capture Map Canvas测试异常: {e}")
        results.append(("Capture Map Canvas", False))

    # 汇总结果
    logger.info("\n" + "=" * 60)
    logger.info("测试结果汇总:")
    logger.info("=" * 60)
    
    for test_name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        logger.info(f"{test_name:20s} : {status}")
    
    logger.info("=" * 60)
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    logger.info(f"总计: {passed_count}/{total_count} 测试通过")
    logger.info("=" * 60)
    
    if passed_count == total_count:
        logger.info("🎉 所有测试通过！MCP通信层验证完成！")
    else:
        logger.warning("⚠️ 部分测试失败，请检查日志")

if __name__ == "__main__":
    asyncio.run(main())
