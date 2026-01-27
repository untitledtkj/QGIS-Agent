#!/usr/bin/env python3
"""
Executor Node测试
"""

import asyncio
from dotenv import load_dotenv

# 加载.env环境变量
load_dotenv()

from agent.state import create_initial_state, Plan, Step, StepContext, RelevantDoc
from agent.nodes.executor_node import executor_node


async def test_executor_node():
    """测试Executor Node"""
    print("测试Executor Node...")
    print("-" * 60)
    
    # 创建测试状态
    state = create_initial_state(
        session_id="test_executor_001",
        input_query="打印QGIS版本信息"
    )
    
    # 创建简单的测试计划
    plan = Plan(
        task="打印QGIS版本",
        steps=[
            Step(
                step_id=1,
                description="打印QGIS版本信息",
                gdal_api=[],
                pyqgis_api=[]
            )
        ],
        metadata={}
    )
    
    state["plan"] = plan
    state["status"] = True
    state["current_step_id"] = 0
    state["api_context_structured"] = [
        StepContext(
            step_id=1,
            relevant_docs=[]
        )
    ]
    
    # 调用Executor Node
    result = await executor_node(state)
    
    print("\nExecutor结果:")
    print(f"- 当前步骤ID: {result.get('current_step_id')}")
    print(f"- 重试次数: {result.get('retry_attempts')}")
    print(f"- 执行日志数: {len(result.get('execution_logs', []))}")
    print(f"- 代码历史数: {len(result.get('code_history', []))}")
    
    if result.get('execution_logs'):
        for log in result['execution_logs']:
            print(f"\n步骤 {log.get('step_id')}: {log.get('status')}")
            if log.get('code'):
                print(f"代码:\n{log['code'][:100]}...")
            if log.get('error_detail'):
                print(f"错误: {log['error_detail']}")
    
    print("\n✅ Executor Node测试通过")


if __name__ == "__main__":
    print("运行Executor Node测试...")
    print("注意: 需要设置OPENAI_API_KEY环境变量")
    print("注意: 需要QGIS MCP插件和MCP Server运行")
    print("=" * 60)
    
    try:
        asyncio.run(test_executor_node())
        
        print("\n" + "=" * 60)
        print("Executor Node测试完成！")
        print("=" * 60)
    
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
