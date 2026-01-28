#!/usr/bin/env python3
"""
Agent Graph人工测试脚本
演示如何使用HITL (Human-in-the-Loop) 机制
"""

import sys
import os
import json
from typing import Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.graph import get_graph
from agent.state import create_initial_state


def print_plan(plan):
    """打印计划详情"""
    if not plan:
        print("  ❌ 计划为空")
        return
    
    print(f"\n  任务: {plan.task}")
    print(f"\n  执行步骤（共{len(plan.steps)}步）:")
    for step in plan.steps:
        print(f"\n    步骤 {step.step_id}: {step.description}")
        if step.gdal_api:
            print(f"      GDAL API: {', '.join(step.gdal_api)}")
        if step.pyqgis_api:
            print(f"      PyQGIS API: {', '.join(step.pyqgis_api)}")


def review_plan() -> tuple[bool, Optional[str]]:
    """
    让用户审核计划
    
    Returns:
        (是否批准, 修改意见)
    """
    print("\n" + "="*60)
    print("📋 计划审核")
    print("="*60)
    print("\n请选择:")
    print("1. 批准计划 - 继续执行")
    print("2. 修改计划 - 提供修改意见")
    print("3. 放弃任务 - 退出执行")
    
    choice = input("\n请输入选择 (1/2/3): ").strip()
    
    if choice == "1":
        return True, None
    elif choice == "2":
        advise = input("\n请输入修改意见: ").strip()
        return False, advise if advise else "请重新规划"
    else:
        return False, None


def review_result(state):
    """
    让用户审核执行结果
    
    Args:
        state: 当前状态
    """
    print("\n" + "="*60)
    print("📊 执行结果审核")
    print("="*60)
    
    # 显示总结
    if state.get("final_summary"):
        print(f"\n总结:\n{state['final_summary']}")
    
    # 显示截图路径
    if state.get("screenshot_path"):
        print(f"\n截图已保存: {state['screenshot_path']}")
    
    # 显示执行日志
    if state.get("execution_logs"):
        print(f"\n执行日志:")
        for log in state["execution_logs"]:
            status = "✅" if log.get("success") else "❌"
            print(f"  {status} 步骤 {log.get('step_id')}: {log.get('message', '')}")
    
    input("\n按Enter键结束...")


def run_agent(user_query: str):
    """
    运行Agent处理用户查询（支持HITL）
    
    Args:
        user_query: 用户的GIS任务需求
    """
    print("\n" + "="*60)
    print("QGIS Agent启动（HITL模式）")
    print("="*60)
    print(f"\n用户查询: {user_query}\n")
    
    # 1. 构建Graph（启用checkpointer支持HITL）
    print("1. 构建Graph...")
    try:
        app = get_graph(
            with_checkpointer=True,
            reset_thread_id="demo_thread"
        )
        print("   ✅ Graph构建成功（已启用状态持久化和人工审核）\n")
    except Exception as e:
        print(f"   ❌ Graph构建失败: {e}")
        print("\n提示: 请确保PostgreSQL数据库正在运行")
        return
    
    # 2. 创建初始状态
    print("2. 创建初始状态...")
    initial_state = create_initial_state(
        session_id="demo_session",
        input_query=user_query
    )
    print(f"   ✅ Session ID: {initial_state['session_id']}\n")
    
    
    # 4. 执行Graph（支持HITL）
    print("\n" + "="*60)
    print("开始执行Graph（HITL模式）")
    print("="*60 + "\n")
    
    config = {
        "configurable": {
            "thread_id": "demo_thread"
        }
    }
    
    try:
        # 执行流程：Graph会自动管理人工审核流程
        print("🚀 开始执行...\n")
        
        current_state = initial_state
        last_step = -1
        
        # Stream执行，遇到人工审核节点时自动中断
        while True:
            final_state = None
            interrupted = False
            
            for chunk in app.stream(current_state, config, stream_mode="values"):
                final_state = chunk
                
                # 显示Planner进度
                if chunk.get("draft") and not chunk.get("plan"):
                    print("✓ Planner生成draft完成")
                
                # 显示执行进度
                if "current_step_id" in chunk:
                    current_step = chunk["current_step_id"]
                    if current_step != last_step:
                        last_step = current_step
                        plan = chunk.get("plan")
                        if plan and current_step < len(plan.steps):
                            print(f"⚙️  执行步骤 {current_step + 1}/{len(plan.steps)}: {plan.steps[current_step].description}")
                
                # 检查是否完成API RAG
                if chunk.get("api_context_structured") and not interrupted:
                    print("✓ API RAG节点完成")
                
                # 检查是否到达Reflector
                if chunk.get("final_summary"):
                    print("✓ Reflector节点完成")
            
            # 检查是否在human_review_node前中断
            if final_state and final_state.get("draft") and not final_state.get("status", False):
                interrupted = True
                print("\n⏸️  到达中断点：计划审核")
                print_plan(final_state["draft"])
                
                # 人工审核
                approved, advise = review_plan()
                
                if advise is None and not approved:
                    # 用户选择放弃
                    print("\n任务已取消")
                    return
                
                if approved:
                    # 批准计划
                    print("\n✅ 计划已批准\n")
                    app.update_state(
                        config,
                        {
                            "plan": final_state["draft"],
                            "status": True
                        }
                    )
                else:
                    # 需要修改
                    print(f"\n📝 修改意见: {advise}")
                    retry_count = final_state.get("retry_count", 0)
                    app.update_state(
                        config,
                        {
                            "advise": advise,
                            "status": False,
                            "draft": None,
                            "retry_count": retry_count + 1
                        }
                    )
                    print("🔄 将根据意见重新规划...\n")
                
                # 继续执行
                current_state = None
            else:
                # 没有中断，执行完成
                break
        
        # 显示最终结果
        if final_state:
            review_result(final_state)
        
        print("\n" + "="*60)
        print("执行完成")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        
        print("\n可能的原因:")
        print("- PostgreSQL数据库未运行或连接失败")
        print("- QGIS MCP服务器未运行")
        print("- LLM API密钥未设置或无效")
        print("- GDAL文档未导入到数据库")


def main():
    """主函数"""
    print("\n" + "="*60)
    print("QGIS Agent Demo - HITL模式")
    print("="*60)
    print("\nGraph结构:")
    print("  Planner → Human Review → API RAG → Executor → Reflector")
    print("\nHITL暂停点:")
    print("  🔄 在Human Review节点前自动中断，等待人工审核")
    print("\n功能特性:")
    print("  ✓ 人工审核计划（由Graph自动管理流程）")
    print("  ✓ 提供修改意见")
    print("  ✓ 支持反复修改计划")
    print("  ✓ 实时执行进度显示")
    print("  ✓ 完整结果展示")
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
    run_agent(query)


if __name__ == "__main__":
    main()
