#!/usr/bin/env python3
"""
Executor Node - 执行器节点
负责代码生成、执行与自主纠错
"""

from typing import Dict, Any, List, Optional, Tuple
import logging
import json
import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import create_model, Field

from agent.state import AgentState, RelevantDoc, StepContext
from agent.tools.database import save_execution_log
from agent.tools.mcp_client import get_mcp_client
from agent.tools.rag import search_gdal_docs, search_pyqgis_docs_async

load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 创建LLM实例（使用思考模型，如deepseek-reasoner）
llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL_NAME", "deepseek-chat"),
    temperature=0.1
)

# 最大重试次数
MAX_RETRY_ATTEMPTS = 3

# 是否支持思考模型（如deepseek-reasoner）
SUPPORT_THINKING_MODEL = os.getenv("SUPPORT_THINKING_MODEL", "true").lower() == "true"

# 状态推送间隔（秒）
STATUS_PUSH_INTERVAL = 5


def _tool_result_to_text(result: Any) -> str:
    """统一将工具返回结果转换为可读文本"""
    if isinstance(result, str):
        return result

    if isinstance(result, ToolMessage):
        content = getattr(result, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            if text_parts:
                return "\n".join(text_parts)
        artifact = getattr(result, "artifact", None)
        if isinstance(artifact, dict) and artifact.get("structured_content") is not None:
            return json.dumps(artifact["structured_content"], ensure_ascii=False)

    if isinstance(result, dict):
        if "error" in result:
            return json.dumps(result.get("error"), ensure_ascii=False)
        if "content" in result:
            content = result.get("content")
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                if text_parts:
                    return "\n".join(text_parts)
            if isinstance(content, str):
                return content
        return json.dumps(result, ensure_ascii=False)

    try:
        return json.dumps(result, ensure_ascii=False)
    except TypeError:
        return str(result)


def _extract_tool_calls(message: AIMessage) -> List[Dict[str, Any]]:
    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls and getattr(message, "additional_kwargs", None):
        tool_calls = message.additional_kwargs.get("tool_calls")
    if not tool_calls:
        return []

    normalized: List[Dict[str, Any]] = []
    for call in tool_calls:
        if "name" in call and "args" in call:
            normalized.append({
                "id": call.get("id"),
                "name": call.get("name"),
                "args": call.get("args") or {},
            })
            continue
        function_call = call.get("function", {}) if isinstance(call, dict) else {}
        name = function_call.get("name")
        arguments = function_call.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except Exception:
                arguments = {"raw": arguments}
        normalized.append({
            "id": call.get("id"),
            "name": name,
            "args": arguments or {},
        })
    return normalized


def _make_runtime_rag_tool(step_context: Optional[StepContext]):
    # Runtime API RAG 暂时停用
    async def _tool(api_names: List[str]) -> str:
        return "Runtime API RAG 已停用"

    def _tool_sync(**_):
        raise RuntimeError("runtime_api_rag 已停用")

    args_schema = create_model(
        "RuntimeApiRagArgs",
        api_names=(List[str], Field(..., description="需要补充的API名称列表")),
    )

    return StructuredTool.from_function(
        name="runtime_api_rag",
        description="运行时补充API文档（GDAL/PyQGIS）- 已停用",
        func=_tool_sync,
        coroutine=_tool,
        args_schema=args_schema,
    )


async def _build_mcp_tools(step_context: Optional[StepContext]) -> Tuple[List[BaseTool], Dict[str, BaseTool], str]:
    mcp_client = await get_mcp_client()
    tools = await mcp_client.get_tools()

    tool_map: Dict[str, BaseTool] = {tool.name: tool for tool in tools}
    tool_lines: List[str] = []
    for tool in tools:
        description = getattr(tool, "description", "") or ""
        tool_lines.append(f"- {tool.name}: {description or '无描述'}")

    # Runtime API RAG 工具暂不注册

    return tools, tool_map, "\n".join(tool_lines)


async def _periodic_status_push(step_id: int, description: str, stop_event: asyncio.Event):
    """
    定期推送任务执行状态
    
    Args:
        step_id: 当前步骤ID
        description: 步骤描述
        stop_event: 停止事件，设置后停止推送
    """
    elapsed_seconds = 0
    
    while not stop_event.is_set():
        await asyncio.sleep(STATUS_PUSH_INTERVAL)
        elapsed_seconds += STATUS_PUSH_INTERVAL
        
        # 推送状态信息（这里输出到日志，实际可以通过SSE推送到前端）
        status_message = f"步骤 {step_id} 正在执行中... ({elapsed_seconds}秒) - {description}"
        logger.info(f"[状态推送] {status_message}")
        
        # TODO: 在实际应用中，可以通过SSE向前端推送状态
        # await sse_client.push_status(status_message)


async def _runtime_api_rag(api_names: List[str], step_context: Optional[StepContext]) -> List[RelevantDoc]:
    """
    Runtime API RAG - 在执行过程中动态补充API文档
    
    Args:
        api_names: 需要补充的API名称列表
        step_context: 当前步骤上下文
        
    Returns:
        补充的API文档列表
    """
    # Runtime API RAG 暂时停用
    logger.info("Runtime API RAG 已停用，跳过补充文档")
    return []


async def _capture_step_screenshot(session_id: str, step_id: int) -> str:
    """
    捕获当前步骤的截图
    
    Args:
        session_id: 会话ID
        step_id: 步骤ID
        
    Returns:
        截图文件路径，失败返回None
    """
    try:
        # 创建截图目录
        screenshot_dir = os.path.join("shared", "screenshots", session_id)
        os.makedirs(screenshot_dir, exist_ok=True)
        
        # 生成截图文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_file = os.path.abspath(
            os.path.join(screenshot_dir, f"step_{step_id}_{timestamp}.png")
        )
        
        # 通过MCP获取截图
        mcp_client = await get_mcp_client()
        await mcp_client.call_tool(
            "capture_map_canvas",
            {"path": screenshot_file, "width": 1200, "height": 800}
        )
        
        # 检查截图是否成功
        if os.path.exists(screenshot_file):
            logger.info(f"步骤{step_id}截图保存成功: {screenshot_file}")
            return screenshot_file
        else:
            logger.warning(f"步骤{step_id}截图文件未生成")
            return None
    
    except Exception as e:
        logger.error(f"捕获步骤{step_id}截图失败: {e}")
        return None


def executor_node(state: AgentState) -> Dict[str, Any]:
    """
    执行器节点 - 生成并执行代码
    
    工作流程:
    1. 获取当前步骤和对应的API文档
    2. 调用LLM生成代码
    3. 通过MCP执行代码
    4. 检查执行结果
    5. 如果失败且未达到重试上限，自主纠错并重试
    6. 更新执行日志和状态
    
    Args:
        state: 当前Agent状态
        
    Returns:
        更新后的状态字段
    """
    import asyncio
    return asyncio.run(_executor_node_async(state))


async def _executor_node_async(state: AgentState) -> Dict[str, Any]:
    """
    执行器节点的异步实现
    """
    logger.info("=" * 60)
    logger.info("Executor Node: 开始执行代码")
    logger.info("=" * 60)
    
    session_id = state["session_id"]
    plan = state.get("plan")
    current_step_id = state.get("current_step_id", 0)
    api_context_structured = state.get("api_context_structured", [])
    execution_logs = state.get("execution_logs", [])
    code_history = state.get("code_history", [])
    retry_attempts = state.get("retry_attempts", 0)
    messages = state.get("messages", [])
    
    if not plan or not plan.steps:
        logger.error("未找到执行计划或步骤为空")
        return {
            "execution_logs": execution_logs,
            "current_step_id": current_step_id,
        }
    
    # 检查是否所有步骤都已完成
    if current_step_id >= len(plan.steps):
        logger.info("所有步骤已完成")
        return {
            "execution_logs": execution_logs,
            "current_step_id": current_step_id,
        }
    
    # 获取当前步骤
    step = plan.steps[current_step_id]
    logger.info(f"执行步骤 {step.step_id}: {step.description}")
    
    # 保存日志
    save_execution_log(
        session_id,
        step.step_id,
        f"开始执行步骤: {step.description}",
        "info"
    )
    
    # 1. 获取该步骤的API文档
    step_context = next(
        (ctx for ctx in api_context_structured if ctx.step_id == step.step_id),
        None
    )
    
    api_context_parts = []
    if step_context and step_context.relevant_docs:
        for doc in step_context.relevant_docs:
            api_context_parts.append(f"### {doc.api_name} ({doc.library})\n{doc.content}\n")
    
    # 2. 构建Prompt与工具集
    tools, tool_map, tool_catalog = await _build_mcp_tools(step_context)
    
    thinking_instruction = ""
    if SUPPORT_THINKING_MODEL:
        thinking_instruction = """\n## 思考过程（可选）
如果需要，你可以使用<thought>标签包裹你的思考过程：
<thought>
这里是你的思考过程，分析任务需求、选择合适的工具、考虑潜在的问题等
</thought>
"""
    
    system_prompt = f"""你是一个专业的QGIS开发专家。你的任务是根据提供的API文档和任务描述，通过工具调用完成当前步骤。

## 当前任务
步骤ID: {step.step_id}
任务描述: {step.description}

## 可用的API文档
{''.join(api_context_parts) if api_context_parts else '未提供API文档'}

## 可用工具
{tool_catalog}
{thinking_instruction}
## 规则
1. **优先使用工具**: 通过工具调用完成任务（例如数据导入和导出），只有在工具不足时才使用 execute_code
2. **环境检查**: 必要时先调用 inspect_qgis_env 或 get_layers 获取当前状态
3. **Runtime API查询**: （已停用）
4. **单步专注**: 只完成当前步骤目标，不要执行后续步骤
5. **文件路径**: 路径必须符合Host OS格式
6. **最终输出**: 当你认为步骤完成，输出“FINAL: ...”简短总结
"""
    
    if retry_attempts > 0 and execution_logs:
        last_log = execution_logs[-1]
        if last_log.get("status") == "error":
            system_prompt += f"""
## 上一次执行失败
错误信息: {last_log.get('error_detail', '未知错误')}
"""
    
    user_message = f"请完成步骤 {step.step_id}: {step.description}"
    
    logger.info("调用LLM进行工具决策与执行...")
    
    try:
        llm_messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ]
        tool_bound_llm = llm.bind_tools(tools)

        tool_actions: List[Dict[str, Any]] = []
        tool_errors: List[str] = []
        final_text: Optional[str] = None
        max_action_rounds = 8

        stop_event = asyncio.Event()
        status_task = asyncio.create_task(
            _periodic_status_push(step.step_id, step.description, stop_event)
        )

        try:
            for round_idx in range(max_action_rounds):
                response = tool_bound_llm.invoke(llm_messages)
                llm_messages.append(response)

                tool_calls = _extract_tool_calls(response)
                if not tool_calls:
                    final_text = (response.content or "").strip()
                    break

                for call_idx, call in enumerate(tool_calls):
                    tool_name = call.get("name")
                    args = call.get("args") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {"raw": args}

                    tool = tool_map.get(tool_name)
                    if not tool:
                        result_text = f"工具不存在: {tool_name}"
                        tool_errors.append(result_text)
                    else:
                        try:
                            result = await tool.ainvoke(args)
                            result_text = _tool_result_to_text(result)
                        except Exception as e:
                            result_text = f"工具执行失败: {tool_name}, {e}"
                            tool_errors.append(result_text)

                    tool_actions.append({
                        "name": tool_name,
                        "args": args,
                        "result": result_text,
                    })

                    if tool_name == "execute_code":
                        code = args.get("code") if isinstance(args, dict) else None
                        if code:
                            code_history.append(code)

                    tool_call_id = call.get("id") or f"{tool_name}_{round_idx}_{call_idx}"
                    llm_messages.append(ToolMessage(content=result_text, tool_call_id=tool_call_id))

            if final_text is None:
                final_text = "未能在限定轮次内完成任务"
                tool_errors.append(final_text)
        finally:
            stop_event.set()
            try:
                await asyncio.wait_for(status_task, timeout=1.0)
            except asyncio.TimeoutError:
                status_task.cancel()

        logger.info(f"步骤 {step.step_id} 执行完成: {final_text}")

        final_lower = (final_text or "").lower()
        is_success = (
            not tool_errors and
            "error" not in final_lower and
            "失败" not in final_text and
            "异常" not in final_text
        )

        if is_success:
            logger.info(f"步骤 {step.step_id} 执行成功")

            execution_logs.append({
                "step_id": step.step_id,
                "description": step.description,
                "status": "success",
                "actions": tool_actions,
                "final": final_text,
            })

            save_execution_log(
                session_id,
                step.step_id,
                f"步骤执行成功: {step.description}",
                "success"
            )

            messages.append(AIMessage(content=f"步骤 {step.step_id} 完成: {final_text}"))

            step_screenshot_path = await _capture_step_screenshot(session_id, step.step_id)
            if step_screenshot_path:
                logger.info(f"步骤 {step.step_id} 截图: {step_screenshot_path}")
                execution_logs[-1]["screenshot"] = step_screenshot_path

            return {
                "current_step_id": current_step_id + 1,
                "execution_logs": execution_logs,
                "code_history": code_history,
                "retry_attempts": 0,
                "messages": messages,
                "screenshot_path": step_screenshot_path,
            }

        error_detail = "；".join(tool_errors) if tool_errors else (final_text or "未知错误")
        logger.error(f"步骤 {step.step_id} 执行失败: {error_detail}")

        execution_logs.append({
            "step_id": step.step_id,
            "description": step.description,
            "status": "error",
            "actions": tool_actions,
            "error_detail": error_detail,
            "final": final_text,
        })

        save_execution_log(
            session_id,
            step.step_id,
            f"步骤执行失败: {error_detail}",
            "error",
            error_detail=error_detail
        )

        if retry_attempts >= MAX_RETRY_ATTEMPTS:
            logger.error(f"步骤 {step.step_id} 达到最大重试次数 ({MAX_RETRY_ATTEMPTS})")
            messages.append(AIMessage(content=f"步骤 {step.step_id} 执行失败（已达到最大重试次数），将跳过该步骤"))
            return {
                "current_step_id": current_step_id + 1,
                "execution_logs": execution_logs,
                "code_history": code_history,
                "retry_attempts": 0,
                "messages": messages,
            }

        logger.info(f"准备重试 (尝试 {retry_attempts + 1}/{MAX_RETRY_ATTEMPTS})...")
        messages.append(AIMessage(content=f"步骤 {step.step_id} 执行失败，准备重试..."))
        return {
            "current_step_id": current_step_id,
            "execution_logs": execution_logs,
            "code_history": code_history,
            "retry_attempts": retry_attempts + 1,
            "messages": messages,
        }
        
    except Exception as e:
        logger.error(f"执行过程中发生异常: {e}")
        
        # 记录异常
        execution_logs.append({
            "step_id": step.step_id,
            "description": step.description,
            "status": "error",
            "error_detail": str(e),
        })
        
        save_execution_log(
            session_id,
            step.step_id,
            f"执行异常: {str(e)}",
            "error",
            error_detail=str(e)
        )
        
        if retry_attempts >= MAX_RETRY_ATTEMPTS:
            logger.error(f"步骤 {step.step_id} 异常达到最大重试次数 ({MAX_RETRY_ATTEMPTS})，将跳过该步骤")
            messages.append(AIMessage(content=f"步骤 {step.step_id} 执行异常（已达到最大重试次数），将跳过该步骤"))
            return {
                "current_step_id": current_step_id + 1,
                "execution_logs": execution_logs,
                "code_history": code_history,
                "retry_attempts": 0,
                "messages": messages,
            }

        return {
            "current_step_id": current_step_id,
            "execution_logs": execution_logs,
            "code_history": code_history,
            "retry_attempts": retry_attempts + 1,
            "messages": messages,
        }
