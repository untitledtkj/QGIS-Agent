#!/usr/bin/env python3
"""
Planner Node - 规划器节点
负责意图识别、Cookbook检索、生成执行计划
"""

from typing import Dict, Any
import logging
import json
import os
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.state import AgentState, Plan, Step
from agent.tools.rag import search_cookbook
from agent.tools.database import save_execution_log

load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 创建LLM实例
llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL_NAME", "deepseek-chat"),
    temperature=0.1
)


def planner_node(state: AgentState) -> Dict[str, Any]:
    """
    规划器节点 - 生成执行计划
    
    工作流程:
    1. 查询重写（综合input_query、log_summary、advise）
    2. 如果是首次规划，检索Cookbook中的相似案例
    3. 调用LLM生成执行计划
    4. 返回draft计划，等待人工审核
    5. 强制退出机制（retry_count >= 3时强制执行）
    
    Args:
        state: 当前Agent状态
        
    Returns:
        更新后的状态字段
    """
    logger.info("=" * 60)
    logger.info("Planner Node: 开始生成执行计划")
    logger.info("=" * 60)
    
    session_id = state["session_id"]
    input_query = state["input_query"]
    advise = state.get("advise")
    log_summary = state.get("log_summary")
    retry_count = state.get("retry_count", 0)
    
    # 保存日志
    save_execution_log(
        session_id,
        None,
        f"开始规划任务: {input_query}",
        "info"
    )
    
    # 强制退出机制：如果重试次数过多，强制执行
    force_execute = retry_count >= 3
    if force_execute:
        logger.warning(f"已达到修改上限（retry_count={retry_count}），将强制执行当前方案")
    
    # 1. 查询重写（Query Rewriting）
    # 综合input_query、log_summary和advise，生成用于检索Cookbook的关键词
    search_query = input_query
    
    if advise or log_summary:
        logger.info("执行查询重写...")
        rewrite_prompt = f"""请将以下信息综合成一个清晰的GIS任务描述，用于检索相似案例。

原始需求: {input_query}

{"上轮执行总结: " + log_summary if log_summary else ""}

{"用户修改意见: " + advise if advise else ""}

请用一句话概括核心任务，包含关键的GIS操作类型（如裁剪、重投影、缓冲区等）。"""

        try:
            response = llm.invoke([HumanMessage(content=rewrite_prompt)])
            search_query = response.content.strip()
            logger.info(f"重写后的查询: {search_query}")
        except Exception as e:
            logger.warning(f"查询重写失败，使用原始查询: {e}")
            search_query = input_query
    
    # 2. 检索相似案例（仅在首次规划时）
    example = None
    if retry_count == 0 and not advise:
        logger.info("检索Cookbook相似案例...")
        cookbook_results = search_cookbook(search_query, similarity_threshold=0.3, top_k=3)
        
        if cookbook_results:
            # 选择最相似的案例
            example = cookbook_results[0]
            logger.info(f"找到相似案例: {example['user_intent'][:50]}... (相似度: {example['similarity_score']:.2f})")
        else:
            logger.info("未找到相似案例")
    
    # 3. 构建Prompt
    system_prompt = """你是一个专业的QGIS地理数据处理专家。你的任务是将用户的自然语言需求转化为可执行的QGIS操作步骤。

## 输出格式
请以JSON格式输出执行计划，包含以下字段：

{
  "task": "任务简述（例如: Align raster and vector layers）",
  "steps": [
    {
      "step_id": 1,
      "description": "步骤描述（例如: Load raster layer from file）",
      "gdal_api": ["可能用到的GDAL API名称"],
      "pyqgis_api": ["可能用到的PyQGIS API名称"]
    }
  ],
  "metadata": {
    "estimated_complexity": "low/medium/high",
    "requires_data": true/false
  }
}

## API命名规范（重要）
请务必使用**完整的API名称格式**：

常用GDAL API示例：
- 打开文件: osgeo.gdal.Open, osgeo.ogr.Open
- 影像处理: osgeo.gdal.Warp, osgeo.gdal.Translate
- 创建数据集: osgeo.gdal.GetDriverByName

常用PyQGIS API示例：
- 图层操作: QgsVectorLayer, QgsRasterLayer
- 项目管理: QgsProject
- 几何操作: QgsGeometry

## 注意事项
1. 步骤不要拆分太细，每个步骤应该是中低复杂度的目标
2. gdal_api和pyqgis_api列出所有可能用到的API名称（不需要参数细节）
3. 参考相似案例可以提高准确性
4. 如果有相似案例，尽量借鉴其代码逻辑
"""
    
    # 构建用户消息
    user_parts = [f"用户需求: {input_query}"]
    
    # 添加上一轮执行总结（如果有）
    if log_summary:
        user_parts.append(f"\n上一轮执行总结:\n{log_summary}")
    
    # 添加用户修改意见（如果有）
    if advise:
        user_parts.append(f"\n用户修改意见:\n{advise}")
    
    # 添加相似案例（如果有）
    if example:
        user_parts.append(f"""
相似案例参考:
- 原始需求: {example['user_intent']}
- 参考代码:
```python
{example['verified_code']}
```
""")
    
    user_message = "\n".join(user_parts)
    
    # 3. 调用LLM生成计划
    logger.info("调用LLM生成执行计划...")
    
    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ]
        
        response = llm.invoke(messages)
        response_text = response.content
        
        logger.info(f"LLM响应: {response_text[:200]}...")
        
        # 解析JSON响应
        # 尝试提取JSON（可能被包裹在```json```中）
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            json_str = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            json_str = response_text[json_start:json_end].strip()
        else:
            json_str = response_text.strip()
        
        plan_dict = json.loads(json_str)
        
        # 转换为Plan对象
        steps = [Step(**step) for step in plan_dict["steps"]]
        plan = Plan(
            task=plan_dict["task"],
            steps=steps,
            metadata=plan_dict.get("metadata", {})
        )
        
        logger.info(f"生成计划成功: {plan.task}, 共{len(plan.steps)}个步骤")
        
        # 保存日志
        save_execution_log(
            session_id,
            None,
            f"生成执行计划: {plan.task}",
            "success"
        )
        
        # 强制执行逻辑：如果已达到修改上限，直接将draft转为plan并标记为已批准
        if force_execute:
            logger.warning("强制执行模式：跳过人工审核，直接执行计划")
            return {
                "draft": plan,
                "plan": plan,  # 直接设置为最终计划
                "example": example,
                "retry_count": retry_count + 1,
                "status": True,  # 标记为已批准
            }
        
        # 正常流程：返回draft等待人工审核
        return {
            "draft": plan,
            "example": example,
            "retry_count": retry_count + 1,
            "status": False,  # 等待人工审核
        }
        
    except Exception as e:
        logger.error(f"生成计划失败: {e}")
        save_execution_log(
            session_id,
            None,
            f"生成计划失败: {str(e)}",
            "error",
            error_detail=str(e)
        )
        
        # 返回错误状态
        return {
            "draft": None,
            "status": False,
            "retry_count": retry_count + 1,
        }
