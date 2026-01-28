#!/usr/bin/env python3
"""
LangGraph 构建模块
定义Agent的状态机、节点连接和执行流程
"""

import os
from typing import Optional, Literal
from dotenv import load_dotenv

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

from agent.state import AgentState
from agent.nodes.planner_node import planner_node
from agent.nodes.api_rag_node import api_rag_node
from agent.nodes.executor_node import executor_node
from agent.nodes.reflector_node import reflector_node_sync

load_dotenv()


def should_continue_planning(state: AgentState) -> Literal["api_rag_node", "planner_node"]:
    """
    判断规划是否完成，是否需要继续修改
    
    逻辑:
    - 如果plan已存在且status=True（已批准），直接进入API RAG
    - 如果status=True但plan不存在，需要先将draft转为plan
    - 如果retry_count>=3（强制退出），进入API RAG
    - 否则返回planner_node继续修改
    
    Args:
        state: 当前状态
        
    Returns:
        下一个节点名称
    """
    # 优先检查：如果已有批准的plan，直接执行
    if state.get("plan") and state.get("status", False):
        return "api_rag_node"
    
    # 其次检查：是否达到重试上限
    if state.get("retry_count", 0) >= 3:
        return "api_rag_node"
    
    # 检查：是否已批准draft（需要转换为plan）
    if state.get("status", False) and state.get("draft"):
        # 这种情况应该在planner_node中处理（将draft转为plan）
        # 但为了安全，这里也返回api_rag_node
        return "api_rag_node"
    
    # 默认：继续规划
    return "planner_node"


def should_continue_execution(state: AgentState) -> Literal["reflector_node", "executor_node"]:
    """
    判断执行是否完成，是否需要继续执行下一步
    
    逻辑:
    - 如果current_step_id >= 步骤总数，进入Reflector
    - 否则继续执行下一步
    
    Args:
        state: 当前状态
        
    Returns:
        下一个节点名称
    """
    plan = state.get("plan")
    if not plan:
        return "reflector_node"
    
    current_step = state.get("current_step_id", 0)
    total_steps = len(plan.steps) if hasattr(plan, 'steps') else 0
    
    if current_step >= total_steps:
        return "reflector_node"
    return "executor_node"


def build_graph(
    checkpointer: Optional[PostgresSaver] = None,
    interrupt_before: Optional[list] = None,
    interrupt_after: Optional[list] = None
) -> StateGraph:
    """
    构建LangGraph状态图
    
    工作流程:
    1. Planner Node -> (条件判断) -> API RAG Node 或继续修改
    2. API RAG Node -> Executor Node
    3. Executor Node -> (循环执行所有步骤) -> Reflector Node
    4. Reflector Node -> END
    
    HITL机制（需要checkpointer）:
    - interrupt_before: 在指定节点之前中断（例如["api_rag_node"]用于计划审核）
    - interrupt_after: 在指定节点之后中断（例如["reflector_node"]用于结果确认）
    
    Args:
        checkpointer: PostgreSQL checkpointer，用于状态持久化和HITL
        interrupt_before: 在这些节点之前中断
        interrupt_after: 在这些节点之后中断
        
    Returns:
        编译后的StateGraph
    """
    # 创建状态图
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("planner_node", planner_node)
    workflow.add_node("api_rag_node", api_rag_node)
    workflow.add_node("executor_node", executor_node)
    workflow.add_node("reflector_node", reflector_node_sync)
    
    # 设置入口点
    workflow.set_entry_point("planner_node")
    
    # 添加边连接
    # Planner -> 条件判断 -> API RAG 或继续修改
    workflow.add_conditional_edges(
        "planner_node",
        should_continue_planning,
        {
            "api_rag_node": "api_rag_node",
            "planner_node": "planner_node"  # 用户修改意见后重新规划
        }
    )
    
    # API RAG -> Executor（直连）
    workflow.add_edge("api_rag_node", "executor_node")
    
    # Executor -> 条件判断 -> 继续执行或进入Reflector
    workflow.add_conditional_edges(
        "executor_node",
        should_continue_execution,
        {
            "executor_node": "executor_node",  # 循环执行下一步
            "reflector_node": "reflector_node"
        }
    )
    
    # Reflector -> END（任务完成）
    workflow.add_edge("reflector_node", END)
    
    # 编译Graph
    # 注意：interrupt功能需要checkpointer支持
    if checkpointer:
        compile_kwargs = {"checkpointer": checkpointer}
        if interrupt_before:
            compile_kwargs["interrupt_before"] = interrupt_before
        if interrupt_after:
            compile_kwargs["interrupt_after"] = interrupt_after
        app = workflow.compile(**compile_kwargs)
    else:
        app = workflow.compile()
    
    return app


def create_checkpointer() -> PostgresSaver:
    """
    创建PostgreSQL checkpointer用于状态持久化
    
    Returns:
        PostgresSaver实例
    """
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/qgis_db")
    
    pool = ConnectionPool(
        conninfo=db_url,
        max_size=10
    )
    
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()  # 创建必要的表结构
    
    return checkpointer


def get_graph(with_checkpointer: bool = True, interrupt_before: list = None, interrupt_after: list = None) -> StateGraph:
    """
    获取配置好的Graph实例
    
    Args:
        with_checkpointer: 是否启用状态持久化
        interrupt_before: 在这些节点之前中断
        interrupt_after: 在这些节点之后中断
        
    Returns:
        编译后的StateGraph
    """
    if with_checkpointer:
        checkpointer = create_checkpointer()
        return build_graph(checkpointer, interrupt_before=interrupt_before, interrupt_after=interrupt_after)
    else:
        return build_graph(interrupt_before=interrupt_before, interrupt_after=interrupt_after)


if __name__ == "__main__":
    # 测试Graph构建
    print("Building LangGraph...")
    app = get_graph(with_checkpointer=False)
    print("Graph built successfully!")
    print("\nGraph structure:")
    print(app.get_graph().draw_mermaid())
