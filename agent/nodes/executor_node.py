#!/usr/bin/env python3
"""
Executor Revise - 使用 create_agent API 的简化版执行器
使用 LangChain 官方推荐的 create_agent 构建执行器，支持手动划定工具范围
"""

from typing import Dict, Any, List, Optional
import logging
import os
from datetime import datetime
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from agent.state import AgentState, StepContext
from agent.tools.mcp_client import get_mcp_client

load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 创建 LLM 实例
llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL_NAME", "deepseek-chat"),
    temperature=0.1
)


def _filter_tools_by_selection(
    all_tools: List[BaseTool],
    tool_selection: Optional[List[str]]
) -> List[BaseTool]:
    """
    根据用户选择的工具列表筛选工具

    Args:
        all_tools: 所有可用工具
        tool_selection: 工具名称列表，None 表示使用全部工具

    Returns:
        筛选后的工具列表
    """
    if tool_selection is None:
        # 默认使用全部工具
        return all_tools

    if not isinstance(tool_selection, list):
        logger.warning(f"tool_selection 必须是工具名称列表，当前类型: {type(tool_selection)}")
        return all_tools

    tool_map = {tool.name: tool for tool in all_tools}
    selected_names = set(tool_selection)
    return [tool_map[name] for name in selected_names if name in tool_map]


async def _get_available_tools() -> List[BaseTool]:
    """
    从 MCP 客户端获取所有可用工具

    Returns:
        工具列表
    """
    mcp_client = await get_mcp_client()
    tools = await mcp_client.get_tools()
    return tools


def _build_system_prompt(
    task_description: str,
    steps_text: str,
    api_context_parts: List[str],
    tool_catalog: str
) -> str:
    """
    构建系统提示词

    Args:
        task_description: 任务描述（task）
        steps_text: 步骤文本（所有步骤）
        api_context_parts: API 上下文部分
        tool_catalog: 工具目录（可用工具列表）

    Returns:
        系统提示词字符串
    """
    prompt = f"""你是一个专业的QGIS开发专家。你的任务是根据提供的API文档和任务描述，通过工具调用完成任务。

## 任务描述
{task_description}

## 执行步骤
{steps_text}

## 可用的API文档
{''.join(api_context_parts) if api_context_parts else '未提供API文档'}

## 可用工具
{tool_catalog}

## 规则
1. **优先使用工具**: 通过工具调用完成任务（例如数据导入和导出），只有在工具不足时才使用 execute_code
2. **完成任务**: 根据任务和执行步骤，逐步完成任务
3. **文件路径**: 路径必须符合Host OS格式
4. **最终输出**: 当你认为任务完成，输出简短总结
"""

    return prompt


async def _create_revise_agent(
    tools: List[BaseTool],
    system_prompt: str
):
    """
    使用 create_agent 创建执行器 agent

    Args:
        tools: 可用工具列表
        system_prompt: 系统提示词

    Returns:
        LangChain Agent 实例
    """
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
    )
    return agent


async def _capture_final_screenshot(session_id: str) -> Optional[str]:
    """
    捕获任务完成后的截图（使用时间戳命名）

    Args:
        session_id: 会话ID

    Returns:
        截图文件路径，失败返回 None
    """
    try:
        # 创建截图目录
        screenshot_dir = os.path.join("shared", "screenshots", session_id)
        os.makedirs(screenshot_dir, exist_ok=True)

        # 生成截图文件名（使用时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_file = os.path.abspath(
            os.path.join(screenshot_dir, f"final_{timestamp}.png")
        )

        # 通过 MCP 获取截图
        mcp_client = await get_mcp_client()
        await mcp_client.call_tool(
            "capture_map_canvas",
            {"path": screenshot_file, "width": 1200, "height": 800}
        )

        # 检查截图是否成功
        if os.path.exists(screenshot_file):
            logger.info(f"最终截图保存成功: {screenshot_file}")
            return screenshot_file
        else:
            logger.warning("最终截图文件未生成")
            return None

    except Exception as e:
        logger.error(f"捕获最终截图失败: {e}")
        return None


async def executor_node(state: AgentState) -> Dict[str, Any]:
    """
    执行器节点（修订版）- 使用 create_agent API

    工作流程:
    1. 从 MCP 获取工具列表，并根据 state 中的 tool_selection 筛选工具
    2. 构建系统提示词（包含 plan 完整信息、步骤和 API 文档）
    3. 使用 create_agent 创建 agent
    4. 调用 agent.ainvoke() 执行任务（ReAct 循环由 agent 内部处理）
    5. 全部执行完后截图
    6. 更新 messages

    Args:
        state: 当前 Agent 状态

        state 中可用的工具选择参数:
            - state.get("tool_selection"): 工具名称列表
                * None: 使用全部工具（默认）
                * ["tool1", "tool2", ...]: 手动指定的工具名称列表

    Returns:
        更新后的状态字段（messages 和 screenshot_path）
    """
    return await _executor_revise_node_async(state)


async def _executor_revise_node_async(state: AgentState) -> Dict[str, Any]:
    """
    执行器节点的异步实现 - 一次性执行整个 plan
    """
    logger.info("=" * 60)
    logger.info("Executor Revise Node: 开始执行任务")
    logger.info("=" * 60)

    session_id = state["session_id"]
    plan = state.get("plan")
    api_context_structured = state.get("api_context_structured", [])
    messages = state.get("messages", [])
    tool_selection = state.get("tool_selection")  # 工具选择范围

    if not plan:
        logger.error("未找到执行计划")
        return {"messages": messages}

    logger.info(f"任务描述: {plan.task}")
    logger.info(f"工具选择范围: {tool_selection if tool_selection else '全部工具'}")

    # 1. 构建 API 文档上下文（合并所有步骤的文档）
    api_context_parts = []
    if api_context_structured:
        for step_context in api_context_structured:
            if step_context.relevant_docs:
                for doc in step_context.relevant_docs:
                    api_context_parts.append(f"### {doc.api_name} ({doc.library})\n{doc.content}\n")

    # 2. 获取所有可用工具
    all_tools = await _get_available_tools()
    logger.info(f"从 MCP 获取到 {len(all_tools)} 个可用工具")

    # 3. 根据用户选择筛选工具范围
    selected_tools = _filter_tools_by_selection(all_tools, tool_selection)
    logger.info(f"筛选后的工具数量: {len(selected_tools)}")
    for tool in selected_tools:
        logger.info(f"  - {tool.name}: {tool.description or '无描述'}")

    # 构建工具目录文本
    tool_catalog = "\n".join([
        f"- {tool.name}: {tool.description or '无描述'}"
        for tool in selected_tools
    ])

    # 构建步骤文本（包含所有步骤）
    steps_text = ""
    if plan.steps:
        for step in plan.steps:
            steps_text += f"{step.step_id}. {step.description}\n"
    else:
        steps_text = "（无具体步骤）"

    # 4. 构建系统提示词
    system_prompt = _build_system_prompt(
        plan.task,
        steps_text,
        api_context_parts,
        tool_catalog
    )

    user_message = f"请完成以下任务: {plan.task}"

    logger.info("使用 create_agent 创建 agent 并执行任务...")

    # 5. 创建 agent
    agent = await _create_revise_agent(selected_tools, system_prompt)

    # 6. 调用 agent.ainvoke() 执行任务
    result = await agent.ainvoke({
        "messages": [HumanMessage(content=user_message)]
    })

    # 提取最终结果
    agent_messages = result.get("messages", [])
    final_message = agent_messages[-1] if agent_messages else None

    if not final_message:
        logger.error("Agent 未返回任何消息")
        raise RuntimeError("Agent 未返回任何消息")

    final_text = final_message.content if final_message.content else ""
    logger.info(f"Agent 执行完成: {final_text}")

    # 7. 更新 messages
    messages.append(AIMessage(content=f"任务完成: {final_text}"))

    # 8. 全部执行完后截图
    screenshot_path = await _capture_final_screenshot(session_id)
    if screenshot_path:
        logger.info(f"任务截图: {screenshot_path}")

    return {
        "messages": messages,
        "screenshot_path": screenshot_path,
    }
