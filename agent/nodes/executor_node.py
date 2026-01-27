#!/usr/bin/env python3
"""
Executor Node - 执行器节点
负责代码生成、执行与自主纠错
"""

from typing import Dict, Any, List
import logging
import json
import os
from datetime import datetime
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.state import AgentState, RelevantDoc, StepContext
from agent.tools.database import save_execution_log
from agent.tools.mcp_client import get_mcp_client
from agent.tools.rag import search_gdal_docs, search_pyqgis_docs

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


async def _runtime_api_rag(api_names: List[str], step_context: StepContext) -> List[RelevantDoc]:
    """
    Runtime API RAG - 在执行过程中动态补充API文档
    
    Args:
        api_names: 需要补充的API名称列表
        step_context: 当前步骤上下文
        
    Returns:
        补充的API文档列表
    """
    logger.info(f"Runtime API RAG: 补充{len(api_names)}个API文档")
    
    supplemental_docs = []
    
    # 分离GDAL和PyQGIS API
    gdal_apis = [api for api in api_names if 'osgeo' in api or 'gdal' in api.lower() or 'ogr' in api.lower()]
    pyqgis_apis = [api for api in api_names if api not in gdal_apis]
    
    try:
        # 检索GDAL文档
        if gdal_apis:
            gdal_results = search_gdal_docs(gdal_apis)
            for doc in gdal_results:
                supplemental_docs.append(RelevantDoc(
                    api_name=doc["api_name"],
                    library="GDAL",
                    content=f"API名称: {doc['api_name']}\n\n描述: {doc['description']}\n\n参数:\n{doc['params']}\n\n示例:\n{doc.get('example_code', '')}"
                ))
        
        # 检索PyQGIS文档
        if pyqgis_apis:
            pyqgis_results = search_pyqgis_docs(pyqgis_apis)
            for doc in pyqgis_results:
                supplemental_docs.append(RelevantDoc(
                    api_name=doc["api_name"],
                    library="PyQGIS",
                    content=doc["content"]
                ))
        
        logger.info(f"Runtime API RAG: 成功补充{len(supplemental_docs)}个API文档")
        
    except Exception as e:
        logger.error(f"Runtime API RAG失败: {e}")
    
    return supplemental_docs


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
        result = await mcp_client.capture_screenshot(
            path=screenshot_file,
            width=1200,
            height=800,
            timeout=10
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
    
    # 2. 构建Prompt
    thinking_instruction = ""
    if SUPPORT_THINKING_MODEL:
        thinking_instruction = """\n## 思考过程（可选）
如果需要，你可以使用<thought>标签包裹你的思考过程：
<thought>
这里是你的思考过程，分析任务需求、选择合适的API、考虑潜在的问题等
</thought>

然后输出代码。思考过程不会被执行，仅用于记录推理链。
"""
    
    system_prompt = f"""你是一个专业的QGIS Python开发专家。你的任务是根据提供的API文档和任务描述，生成可执行的PyQGIS/GDAL代码。

## 当前任务
步骤ID: {step.step_id}
任务描述: {step.description}

## 可用的API文档
{''.join(api_context_parts) if api_context_parts else '未提供API文档'}
{thinking_instruction}
## 代码生成要求
1. **严格参考API文档**: 参数名称、类型必须与文档完全一致，不要臆造参数
2. **防御性编程**: 在执行前检查文件是否存在、图层是否已加载等
3. **错误处理**: 使用try-except捕获异常，并打印清晰的错误信息
4. **单步专注**: 只完成当前步骤的目标，不要执行后续步骤
5. **文件路径**: 确保文件路径符合Host OS格式（Windows用反斜杠，Linux/Mac用正斜杠）
6. **输出信息**: 使用print()输出关键信息，便于调试
7. **Runtime API查询**: 如果发现需要的API文档缺失，在代码注释中标注#NEED_API: api_name，系统会自动补充

## 输出格式
只输出Python代码，不要包含任何解释文字或markdown标记。
"""
    
    # 如果是重试，添加错误信息
    if retry_attempts > 0 and execution_logs:
        last_log = execution_logs[-1]
        if last_log.get("status") == "error":
            system_prompt += f"""
## 上一次执行失败
错误信息: {last_log.get('error_detail', '未知错误')}

请分析错误原因并修正代码。
"""
    
    user_message = f"请为步骤 {step.step_id} 生成代码: {step.description}"
    
    # 3. 调用LLM生成代码
    logger.info("调用LLM生成代码...")
    
    try:
        llm_messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ]
        
        response = llm.invoke(llm_messages)
        raw_response = response.content.strip()
        
        # 提取思考过程（如果有）
        thought_content = ""
        generated_code = raw_response
        
        if SUPPORT_THINKING_MODEL and "<thought>" in raw_response and "</thought>" in raw_response:
            import re
            thought_match = re.search(r'<thought>(.*?)</thought>', raw_response, re.DOTALL)
            if thought_match:
                thought_content = thought_match.group(1).strip()
                # 移除思考标签，保留代码
                generated_code = re.sub(r'<thought>.*?</thought>', '', raw_response, flags=re.DOTALL).strip()
                logger.info(f"提取到思考过程（{len(thought_content)}字符）: {thought_content[:100]}...")
        
        # 清理代码（移除可能的markdown包裹）
        if generated_code.startswith("```python"):
            generated_code = generated_code[9:]
        if generated_code.startswith("```"):
            generated_code = generated_code[3:]
        if generated_code.endswith("```"):
            generated_code = generated_code[:-3]
        
        generated_code = generated_code.strip()
        
        # 检查是否需要Runtime API补充
        import re
        need_apis = re.findall(r'#\s*NEED_API:\s*([\w\.]+)', generated_code)
        if need_apis:
            logger.info(f"检测到需要补充的API: {need_apis}")
            # Runtime API RAG补充
            supplemental_docs = await _runtime_api_rag(need_apis, step_context)
            if supplemental_docs:
                logger.info(f"补充了{len(supplemental_docs)}个API文档")
                # 将补充文档添加到上下文并重新生成代码
                for doc in supplemental_docs:
                    api_context_parts.append(f"### {doc.api_name} ({doc.library})\n{doc.content}\n")
                # 更新system_prompt并重新调用
                # （这里简化处理，实际可以递归调用）
        
        logger.info(f"生成代码（{len(generated_code)}字符）:\n{generated_code[:200]}...")
        
        # 记录思考过程到messages
        if thought_content:
            messages.append(AIMessage(content=f"思考: {thought_content}"))
        
        # 记录代码
        code_history.append(generated_code)
        
        # 4. 执行代码
        logger.info("通过MCP执行代码...")
        
        mcp_client = await get_mcp_client()
        result = await mcp_client.execute_code(generated_code, timeout=120)
        
        logger.info(f"执行结果: {result}")
        
        # 5. 解析执行结果
        result_content = result.get("result", {}).get("content", [])
        
        if not result_content:
            raise Exception("MCP返回结果为空")
        
        # 提取执行结果文本
        result_text = ""
        for content_item in result_content:
            if content_item.get("type") == "text":
                result_text += content_item.get("text", "")
        
        logger.debug(f"MCP原始返回: {result_text[:500]}")
        
        # 解析result_text中的JSON
        # MCP可能返回多种格式:
        # 1. {'status': 'success', 'result': {...}}
        # 2. {'result': 'null'} 或 {'result': {...}}
        # 3. 纯文本输出
        try:
            # 尝试提取最后一个包含result的JSON对象
            import re
            
            # 查找所有JSON对象
            json_objects = re.findall(r'\{[^{}]*\}', result_text)
            
            execution_result = None
            for json_str in reversed(json_objects):  # 从后往前找
                try:
                    parsed = json.loads(json_str)
                    if "result" in parsed or "status" in parsed:
                        execution_result = parsed
                        break
                except:
                    continue
            
            if not execution_result:
                # 未找到有效JSON，使用整个文本
                execution_result = {"status": "unknown", "result": result_text}
            
            # 检查是否有明确的status字段
            if "status" not in execution_result:
                # 根据result字段判断
                result_value = execution_result.get("result")
                if result_value == "null" or result_value is None:
                    # null可能表示执行成功但无返回值
                    execution_result["status"] = "success"
                elif isinstance(result_value, dict) and "executed" in result_value:
                    execution_result["status"] = "success" if result_value["executed"] else "error"
                else:
                    execution_result["status"] = "success"  # 有返回值视为成功
                    
        except Exception as e:
            logger.warning(f"解析MCP结果失败: {e}, 使用原始文本")
            execution_result = {"status": "unknown", "result": result_text}
        
        # 6. 检查执行状态
        status = execution_result.get("status", "unknown")
        
        logger.info(f"解析后的执行状态: {status}, 完整结果: {execution_result}")
        
        # 当status为success或unknown（且result不是error）时视为成功
        is_success = (status == "success") or (
            status == "unknown" and 
            "error" not in str(execution_result.get("result", "")).lower() and
            "exception" not in str(execution_result.get("result", "")).lower()
        )
        
        if is_success:
            logger.info(f"步骤 {step.step_id} 执行成功")
            
            # 记录执行日志
            execution_logs.append({
                "step_id": step.step_id,
                "description": step.description,
                "status": "success",
                "code": generated_code,
                "output": execution_result.get("result", {}),
            })
            
            save_execution_log(
                session_id,
                step.step_id,
                f"步骤执行成功: {step.description}",
                "success"
            )
            
            # 更新消息
            messages.append(AIMessage(content=f"步骤 {step.step_id} 代码:\n```python\n{generated_code}\n```"))
            messages.append(HumanMessage(content=f"执行成功"))
            
            # 每步成功后生成截图
            step_screenshot_path = await _capture_step_screenshot(session_id, step.step_id)
            if step_screenshot_path:
                logger.info(f"步骤 {step.step_id} 截图: {step_screenshot_path}")
                execution_logs[-1]["screenshot"] = step_screenshot_path
            
            # 移动到下一步，重置重试计数
            return {
                "current_step_id": current_step_id + 1,
                "execution_logs": execution_logs,
                "code_history": code_history,
                "retry_attempts": 0,
                "messages": messages,
                "screenshot_path": step_screenshot_path,  # 保存最新截图
            }
        
        else:
            # 执行失败
            error_detail = execution_result.get("message", "未知错误")
            logger.error(f"步骤 {step.step_id} 执行失败: {error_detail}")
            
            # 记录执行日志
            execution_logs.append({
                "step_id": step.step_id,
                "description": step.description,
                "status": "error",
                "code": generated_code,
                "error_detail": error_detail,
            })
            
            save_execution_log(
                session_id,
                step.step_id,
                f"步骤执行失败: {error_detail}",
                "error",
                error_detail=error_detail
            )
            
            # 检查是否达到重试上限
            if retry_attempts >= MAX_RETRY_ATTEMPTS:
                logger.error(f"步骤 {step.step_id} 达到最大重试次数 ({MAX_RETRY_ATTEMPTS})")
                
                messages.append(AIMessage(content=f"步骤 {step.step_id} 执行失败（已达到最大重试次数）"))
                
                return {
                    "current_step_id": current_step_id,
                    "execution_logs": execution_logs,
                    "code_history": code_history,
                    "retry_attempts": retry_attempts + 1,
                    "messages": messages,
                }
            else:
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
        
        return {
            "current_step_id": current_step_id,
            "execution_logs": execution_logs,
            "code_history": code_history,
            "retry_attempts": retry_attempts + 1,
            "messages": messages,
        }
