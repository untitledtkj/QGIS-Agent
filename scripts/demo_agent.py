#!/usr/bin/env python3
"""
Agent Graph快速启动脚本
演示如何使用构建好的Graph
"""

import sys
import os
import asyncio

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.graph import get_graph
from agent.state import create_initial_state


async def run_agent(user_query: str):
    """
    运行Agent处理用户查询
    
    Args:
        user_query: 用户的GIS任务需求
    """
    print("\n" + "="*60)
    print("QGIS Agent启动")
    print("="*60)
    print(f"\n用户查询: {user_query}\n")
    
    # 1. 构建Graph（不使用checkpointer以简化演示）
    print("1. 构建Graph...")
    app = get_graph(with_checkpointer=False)
    print("   ✅ Graph构建成功\n")
    
    # 2. 创建初始状态
    print("2. 创建初始状态...")
    initial_state = create_initial_state(
        session_id="demo_session",
        input_query=user_query
    )
    print(f"   ✅ Session ID: {initial_state['session_id']}\n")
    
    # 3. 准备执行
    print("="*60)
    print("准备执行Graph")
    print("="*60)
    print("\n注意: 完整执行需要:")
    print("1. ✅ OPENAI_API_KEY环境变量已设置")
    print("2. ⚠️  PostgreSQL数据库正在运行（localhost:5432）")
    print("3. ⚠️  QGIS MCP服务器正在运行（localhost:8080）")
    print("4. ⚠️  GDAL文档已导入到数据库")
    print("\n如果缺少任何依赖，执行将会失败。")
    
    user_input = input("\n是否继续执行? (y/N): ")
    
    if user_input.lower() != 'y':
        print("\n取消执行")
        return
    
    # 4. 执行Graph
    print("\n" + "="*60)
    print("开始执行Graph")
    print("="*60 + "\n")
    
    try:
        # 由于配置了interrupt点，实际执行会在以下位置暂停:
        # - interrupt_before: api_rag_node (Planner审核后)
        # - interrupt_after: reflector_node (Reflector完成后)
        
        config = {
            "configurable": {
                "thread_id": "demo_thread"
            }
        }
        
        print("执行中...\n")
        
        # Stream执行以查看中间结果
        async for event in app.astream_events(initial_state, config, version="v1"):
            if event["event"] == "on_chain_start":
                print(f"▶ 开始: {event['name']}")
            elif event["event"] == "on_chain_end":
                print(f"✓ 完成: {event['name']}")
        
        print("\n" + "="*60)
        print("执行完成（或在interrupt点暂停）")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        
        print("\n可能的原因:")
        print("- PostgreSQL数据库未运行")
        print("- QGIS MCP服务器未运行")
        print("- LLM API密钥未设置或无效")
        print("- GDAL文档未导入到数据库")


def main():
    """主函数"""
    print("\n" + "="*60)
    print("QGIS Agent Demo")
    print("="*60)
    print("\nGraph结构:")
    print("  Planner → API RAG → Executor → Reflector")
    print("\nHITL暂停点:")
    print("  - Planner审核后（interrupt_before: api_rag_node）")
    print("  - Reflector完成后（interrupt_after: reflector_node）")
    print("="*60 + "\n")
    
    # 示例查询
    examples = [
        "加载一个shapefile并将其重投影到WGS84坐标系",
        "对栅格影像进行裁剪和重采样",
        "创建矢量图层的缓冲区分析",
    ]
    
    print("示例查询:")
    for i, example in enumerate(examples, 1):
        print(f"{i}. {example}")
    
    print("\n请输入您的GIS任务需求（或输入数字选择示例）:")
    user_input = input("> ").strip()
    
    if user_input.isdigit() and 1 <= int(user_input) <= len(examples):
        query = examples[int(user_input) - 1]
    elif user_input:
        query = user_input
    else:
        query = examples[0]
        print(f"使用默认查询: {query}")
    
    # 运行Agent
    asyncio.run(run_agent(query))


if __name__ == "__main__":
    main()
