#!/usr/bin/env python3
"""
Reflector Node测试
"""

import asyncio
from dotenv import load_dotenv

# 加载.env环境变量
load_dotenv()

from agent.state import create_initial_state, Plan, Step
from agent.nodes.reflector_node import reflector_node


async def test_reflector_node():
    """测试Reflector Node"""
    print("测试Reflector Node...")
    print("-" * 60)
    
    # 创建测试状态
    state = create_initial_state(
        session_id="test_reflector_001",
        input_query="加载矢量图层测试"
    )
    
    # 创建测试计划
    plan = Plan(
        task="加载矢量图层",
        steps=[
            Step(step_id=1, description="加载shapefile", gdal_api=[], pyqgis_api=[]),
            Step(step_id=2, description="显示图层", gdal_api=[], pyqgis_api=[])
        ],
        metadata={"estimated_complexity": "low"}
    )
    
    # 模拟执行日志
    execution_logs = [
        {
            "step_id": 1,
            "description": "加载shapefile",
            "status": "success",
            "code": "print('步骤1代码')",
            "output": {"executed": True}
        },
        {
            "step_id": 2,
            "description": "显示图层",
            "status": "success",
            "code": "print('步骤2代码')",
            "output": {"executed": True}
        }
    ]
    
    state["plan"] = plan
    state["execution_logs"] = execution_logs
    state["code_history"] = ["print('步骤1代码')", "print('步骤2代码')"]
    
    # 调用Reflector Node
    result = await reflector_node(state)
    
    print("\nReflector结果:")
    print(f"- 最终总结: {result.get('final_summary')[:100] if result.get('final_summary') else None}...")
    print(f"- 质量评分: {result.get('quality_score')}")
    print(f"- 截图路径: {result.get('screenshot_path')}")
    print(f"- 任务完成: {result.get('is_completed')}")
    
    # 检查状态是否清理
    print(f"\n状态清理检查:")
    print(f"- draft: {result.get('draft')}")
    print(f"- plan: {result.get('plan')}")
    print(f"- execution_logs: {len(result.get('execution_logs', []))}")
    print(f"- messages: {len(result.get('messages', []))}")
    
    print("\n✅ Reflector Node测试通过")


if __name__ == "__main__":
    print("运行Reflector Node测试...")
    print("注意: 需要设置OPENAI_API_KEY环境变量")
    print("注意: 需要QGIS MCP插件和MCP Server运行（用于截图）")
    print("=" * 60)
    
    try:
        asyncio.run(test_reflector_node())
        
        print("\n" + "=" * 60)
        print("Reflector Node测试完成！")
        print("=" * 60)
    
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
