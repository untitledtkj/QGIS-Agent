#!/usr/bin/env python3
"""
Reflector Node - 反思与归档节点
负责执行结果总结、价值判断与归档、状态清理
"""

from typing import Dict, Any
import logging
import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from agent.state import AgentState
from agent.tools.database import save_execution_log, save_cookbook_entry
from agent.tools.mcp_client import get_mcp_client

load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 创建LLM实例
llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL_NAME", "deepseek-chat"),
    temperature=0.1
)


async def reflector_node(state: AgentState) -> Dict[str, Any]:
    """
    反思与归档节点 - 总结任务并归档成功案例
    
    工作流程:
    1. 分析执行日志，判断任务是否成功
    2. 生成任务总结
    3. 评估任务价值（质量评分）
    4. 如果值得归档，保存到Cookbook
    5. 生成截图（如果需要）
    6. 清理临时状态
    
    Args:
        state: 当前Agent状态
        
    Returns:
        更新后的状态字段
    """
    logger.info("=" * 60)
    logger.info("Reflector Node: 开始反思与归档")
    logger.info("=" * 60)
    
    session_id = state["session_id"]
    input_query = state["input_query"]
    plan = state.get("plan")
    messages = state.get("messages", [])
    execution_logs = state.get("execution_logs", [])
    
    # 保存日志
    await asyncio.to_thread(
        save_execution_log,
        session_id,
        None,
        "开始任务反思与归档",
        "info"
    )
    
    # 1. 分析执行结果
    total_steps = len(plan.steps) if plan else 0
    is_completed = state.get("is_completed")
    if is_completed is None:
        is_success = len(messages) > 0
    else:
        is_success = bool(is_completed)

    success_count = 1 if is_success else 0
    error_count = 0 if is_success else 1
    
    # 2. 生成任务总结
    logger.info("生成任务总结...")
    
    # 构建执行日志摘要
    log_summary_parts = []

    for msg in messages:
        content = getattr(msg, "content", "") or ""
        if content:
            log_summary_parts.append(f"- {content}")
    
    log_summary_text = "\n".join(log_summary_parts) if log_summary_parts else "无可用日志"
    
    # 提取代码中的关键信息（图层名、变量名）
    layer_names = set()
    variable_names = set()
    
    # for log in execution_logs:
    #     code = log.get("code", "")
    #     if code:
    #         # 提取图层名称（常见模式）
    #         import re
    #         # 匹配 QgsVectorLayer("path", "layer_name", ...)
    #         layer_matches = re.findall(r'QgsVectorLayer\([^,]+,\s*["\']([^"\']+)["\']', code)
    #         layer_names.update(layer_matches)
            
    #         # 匹配 QgsRasterLayer("path", "layer_name")
    #         raster_matches = re.findall(r'QgsRasterLayer\([^,]+,\s*["\']([^"\']+)["\']', code)
    #         layer_names.update(raster_matches)
            
    #         # 匹配 addVectorLayer(..., name="layer_name")
    #         add_layer_matches = re.findall(r'add(?:Vector|Raster)Layer\([^)]*name\s*=\s*["\']([^"\']+)["\']', code)
    #         layer_names.update(add_layer_matches)
            
    #         # 提取变量名（赋值语句）
    #         var_matches = re.findall(r'^(\w+)\s*=\s*(?:Qgs|gdal|ogr)', code, re.MULTILINE)
    #         variable_names.update(var_matches)
    
    # 构建详细信息字符串
    detail_info = ""
    if layer_names:
        detail_info += f"\n图层: {', '.join(sorted(layer_names))}"
    if variable_names:
        detail_info += f"\n变量: {', '.join(sorted(variable_names))}"
    
    # 调用LLM生成总结
    system_prompt = f"""你是一个专业的GIS任务分析专家。请分析以下任务执行情况，生成简洁的总结报告。

总结应包含:
1. 任务完成情况（成功/失败）
2. 关键步骤回顾
3. 使用的图层和变量（如果有）
4. 遇到的问题（如果有）
5. 经验教训（如果有）

请用简洁的中文回答，不超过300字。{detail_info if detail_info else ''}
"""
    
    user_message = f"""
任务需求: {input_query}

执行计划: {plan.task if plan else '无计划'}

执行日志:
{log_summary_text}

总步骤数: {total_steps}
执行结果: {"成功" if is_success else "失败"}
"""
    
    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ]
        
        response = await llm.ainvoke(messages)
        final_summary = response.content.strip()
        
        logger.info(f"生成总结: {final_summary[:100]}...")
        
    except Exception as e:
        logger.error(f"生成总结失败: {e}")
        final_summary = f"任务{'成功' if is_success else '失败'} (总步骤: {total_steps})"
    
    # 3. 评估任务价值
    quality_score = 0.0
    
    if is_success:
        # 成功任务基础分 0.6
        quality_score = 0.6
        
        # 根据复杂度加分
        if total_steps >= 5:
            quality_score += 0.2
        elif total_steps >= 3:
            quality_score += 0.1
        
        # 如果有重试但最终成功，加分（说明有纠错能力）
        if error_count > 0:
            quality_score += 0.1
        
        quality_score = min(quality_score, 1.0)
    else:
        # 失败任务
        quality_score = max(0.0, 0.3 - (error_count * 0.1))
    
    logger.info(f"质量评分: {quality_score:.2f}")
    
    # 4. 人工结项检查 (HITL)
    # 通过interrupt_after机制，用户在UI中确认is_completed
    # 注意：interrupt恢复后，is_completed应该已经由用户设置
    if is_completed is None:
        is_completed = is_success
    logger.info(f"任务完成状态（由用户确认或默认判断）: {is_completed}")
    
    # 5. 归档到Cookbook（技术文档要求: quality_score > 0.6）
    if is_completed and quality_score > 0.6:
        logger.info("任务质量达标，归档到Cookbook...")
        
        # 合并所有成功步骤的代码
        verified_code_parts = []
        for log in execution_logs:
            if log.get("status") == "success" and log.get("code"):
                verified_code_parts.append(f"# 步骤 {log.get('step_id')}: {log.get('description')}")
                verified_code_parts.append(log.get("code"))
                verified_code_parts.append("")  # 空行
        
        verified_code = "\n".join(verified_code_parts)
        
        # 提取标签
        tags = []
        if plan and plan.metadata:
            tags.append(plan.metadata.get("estimated_complexity", "unknown"))
        if total_steps >= 5:
            tags.append("complex")
        
        # 计算复杂度评分
        complexity_score = min(total_steps / 10.0, 1.0)
        
        # 保存到Cookbook
        try:
            entry_id = await asyncio.to_thread(
                save_cookbook_entry,
                user_intent=input_query,
                verified_code=verified_code,
                tags=tags,
                complexity_score=complexity_score,
                metadata={
                    "session_id": session_id,
                    "total_steps": total_steps,
                    "quality_score": quality_score,
                }
            )
            
            if entry_id:
                logger.info(f"成功归档到Cookbook: entry_id={entry_id}")
                await asyncio.to_thread(
                    save_execution_log,
                    session_id,
                    None,
                    f"任务归档到Cookbook: entry_id={entry_id}",
                    "success"
                )
            else:
                logger.warning("归档到Cookbook失败")
        
        except Exception as e:
            logger.error(f"归档到Cookbook时发生异常: {e}")
    
    else:
        logger.info(f"任务不满足归档条件 (完成={is_completed}, 质量={quality_score:.2f})")
    
    # 6. 生成最终截图（如果任务完成）
    screenshot_path = None
    
    if is_success:
        try:
            logger.info("尝试生成截图...")
            
            # 创建截图目录
            screenshot_dir = os.path.join("shared", "screenshots", session_id)
            os.makedirs(screenshot_dir, exist_ok=True)
            
            # 生成截图文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_file = os.path.abspath(
                os.path.join(screenshot_dir, f"final_{timestamp}.png")
            )
            
            # 通过MCP获取截图
            mcp_client = await get_mcp_client()
            await mcp_client.call_tool(
                "capture_map_canvas",
                {"path": screenshot_file, "width": 1200, "height": 800}
            )
            
            # 检查截图是否成功
            if os.path.exists(screenshot_file):
                screenshot_path = screenshot_file
                logger.info(f"截图保存成功: {screenshot_path}")
                await asyncio.to_thread(
                    save_execution_log,
                    session_id,
                    None,
                    f"截图保存: {screenshot_path}",
                    "success"
                )
            else:
                logger.warning("截图文件未生成")
        
        except Exception as e:
            logger.error(f"生成截图失败: {e}")
            await asyncio.to_thread(
                save_execution_log,
                session_id,
                None,
                f"生成截图失败: {str(e)}",
                "warning"
            )
    
    # 6. 状态清理（按照技术文档清理清单）
    # 保留的字段: log_summary, screenshot_path, input_query, is_completed
    # 清理的字段: draft, plan, api_context_structured, execution_logs, code_history, 
    #            advise, retry_count, status, example, missing_deps, messages, quality_score
    logger.info("执行状态清理...")
    
    cleaned_state = {
        # 保留字段
        "final_summary": final_summary,
        "log_summary": final_summary,  # 用于下一轮Planner的上下文
        "screenshot_path": screenshot_path,
        "is_completed": is_completed,  # 待HITL实现后改为人工确认
        
        # 清理的字段（重置为初始值）
        "draft": None,
        "plan": None,
        "api_context_structured": [],
        "gdal_doc": [],
        "pyqgis_doc": [],
        "execution_logs": [],
        "code_history": [],
        "advise": None,
        "retry_count": 0,
        "status": False,
        "example": None,
        "missing_deps": [],
        "messages": [],
        "current_step_id": 0,
        "retry_attempts": 0,
        "quality_score": 0.0,  # 按文档要求清理
    }
    
    # 保存最终日志
    await asyncio.to_thread(
        save_execution_log,
        session_id,
        None,
        f"任务完成: {final_summary[:100]}",
        "success" if is_completed else "error"
    )
    
    logger.info("状态清理完成，节点执行结束")
    
    return cleaned_state


# 仅保留异步版本
