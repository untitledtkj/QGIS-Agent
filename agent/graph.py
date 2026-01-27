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
from agent.nodes.reflector_node import reflector_node

load_dotenv()


def should_continue_planning(state: AgentState) -> Literal["api_rag_node", "planner_node"]:
    """
    判断规划是否完成，是否需要继续修改
    
    逻辑:
    - 如果status=True（用户批准）或retry_count>=3（强制退出），进入API RAG
    - 否则返回planner_node继续修改
    
    Args:
        state: 当前状态
        
    Returns:
        下一个节点名称
    """
    if state.get("status", False) or state.get("retry_count", 0) >= 3:
        return "api_rag_node"
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


def build_graph(checkpointer: Optional[PostgresSaver] = None) -> StateGraph:
    """
    构建LangGraph状态图
    
    工作流程:
    1. Planner Node -> (HITL interrupt) -> API RAG Node
    2. API RAG Node -> Executor Node
    3. Executor Node -> (循环执行所有步骤) -> Reflector Node
    4. Reflector Node -> (HITL interrupt) -> END
    
    Args:
        checkpointer: PostgreSQL checkpointer，用于状态持久化
        
    Returns:
        编译后的StateGraph
    """
    # 创建状态图
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("planner_node", planner_node)
    workflow.add_node("api_rag_node", api_rag_node)
    workflow.add_node("executor_node", executor_node)
    workflow.add_node("reflector_node", reflector_node)
    
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
    # 配置interrupt点用于HITL
    app = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["api_rag_node"],  # Planner审核后暂停
        interrupt_after=["reflector_node"]  # Reflector人工确认后暂停
    )
    
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


def get_graph(with_checkpointer: bool = True) -> StateGraph:
    """
    获取配置好的Graph实例
    
    Args:
        with_checkpointer: 是否启用状态持久化
        
    Returns:
        编译后的StateGraph
    """
    if with_checkpointer:
        checkpointer = create_checkpointer()
        return build_graph(checkpointer)
    else:
        return build_graph()


if __name__ == "__main__":
    # 测试Graph构建
    print("Building LangGraph...")
    app = get_graph(with_checkpointer=False)
    print("Graph built successfully!")
    print("\nGraph structure:")
    print(app.get_graph().draw_mermaid())
