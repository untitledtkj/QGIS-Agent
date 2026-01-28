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
    
    # 1. 构建Graph（启用checkpointer支持HITL，在API RAG前中断）
    print("1. 构建Graph...")
    try:
        app = get_graph(
            with_checkpointer=True,
            interrupt_before=["api_rag_node"]  # 在Planner完成后暂停
        )
        print("   ✅ Graph构建成功（已启用状态持久化）\n")
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
    
    # 3. 准备执行
    print("="*60)
    print("准备执行Graph")
    print("="*60)
    print("\n注意: 完整执行需要:")
    print("1. ✅ OPENAI_API_KEY环境变量已设置")
    print("2. ✅ PostgreSQL数据库正在运行（localhost:5432）")
    print("3. ⚠️  QGIS MCP服务器正在运行（localhost:8080）")
    print("4. ⚠️  GDAL文档已导入到数据库")
    print("\n如果缺少任何依赖，执行将会失败。")
    
    user_input = input("\n是否继续执行? (y/N): ")
    
    if user_input.lower() != 'y':
        print("\n取消执行")
        return
    
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
        # 执行流程
        print("🚀 开始执行...\n")
        
        max_retries = 3
        retry_count = 0
        approved = False
        current_state = initial_state
        
        # 循环：生成计划 -> 审核 -> 批准或修改
        while not approved and retry_count < max_retries:
            # 1. 执行Planner（会在api_rag_node前中断）
            final_state = None
            print(f"⚙️  规划中... (尝试 {retry_count + 1}/{max_retries})")
            
            for chunk in app.stream(current_state, config, stream_mode="values"):
                final_state = chunk
                if chunk.get("draft"):
                    print("✓ Planner生成draft完成")
            
            if not final_state or not final_state.get("draft"):
                print("❌ Planner未生成计划")
                return
            
            # 2. 展示并审核计划
            print("\n⏸️  到达中断点：计划审核")
            print_plan(final_state["draft"])
            
            approved, advise = review_plan()
            
            if advise is None and not approved:
                # 用户选择放弃
                print("\n任务已取消")
                return
            
            if not approved:
                # 用户要求修改，准备下一轮
                print(f"\n📝 修改意见: {advise}")
                retry_count += 1
                
                # 更新状态：设置修改意见，清空draft，重新回到Planner
                app.update_state(
                    config,
                    {
                        "advise": advise,
                        "status": False,
                        "retry_count": retry_count,
                        "draft": None
                    }
                )
                # 从checkpoint继续（从Planner开始）
                current_state = None
                print("🔄 将根据意见重新规划...\n")
            else:
                # 批准，准备执行
                print("\n✅ 计划已批准\n")
                # 更新状态：将draft提升为plan，设置status=True
                app.update_state(
                    config,
                    {
                        "plan": final_state["draft"],
                        "status": True
                    }
                )
        
        # 检查是否超过重试次数
        if not approved:
            print(f"\n⚠️  已达到最大修改次数({max_retries})，使用最后一版计划继续执行\n")
            app.update_state(
                config,
                {
                    "plan": final_state.get("draft"),
                    "status": True,
                    "retry_count": max_retries
                }
            )
        
        # 3. 继续执行剩余节点（API RAG -> Executor -> Reflector）
        print("🚀 开始执行任务...\n")
        
        final_state = None
        last_step = -1
        
        # 从checkpoint继续（stream with None表示从当前中断点继续）
        for chunk in app.stream(None, config, stream_mode="values"):
            final_state = chunk
            
            # 显示执行进度
            if "current_step_id" in chunk:
                current_step = chunk["current_step_id"]
                if current_step != last_step:
                    last_step = current_step
                    plan = chunk.get("plan")
                    if plan and current_step < len(plan.steps):
                        print(f"⚙️  执行步骤 {current_step + 1}/{len(plan.steps)}: {plan.steps[current_step].description}")
            
            # 检查是否完成API RAG
            if chunk.get("api_context_structured"):
                print("✓ API RAG节点完成")
            
            # 检查是否到达Reflector
            if chunk.get("final_summary"):
                print("✓ Reflector节点完成")
        
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
    print("  Planner → API RAG → Executor → Reflector")
    print("\nHITL暂停点:")
    print("  1️⃣  Planner审核 - 审核和修改执行计划")
    print("  2️⃣  Reflector确认 - 查看执行结果")
    print("\n功能特性:")
    print("  ✓ 人工审核计划")
    print("  ✓ 提供修改意见")
    print("  ✓ 最多3次修改机会")
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
