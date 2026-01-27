#!/usr/bin/env python3
"""
运行所有测试的便捷脚本
"""

import subprocess
import sys
import os

# 设置环境变量
os.environ['PYTHONPATH'] = r'D:\own_project\qgis-agentv2'

def run_test(test_file, description):
    """运行单个测试"""
    print("\n" + "="*60)
    print(f"运行测试: {description}")
    print("="*60)
    
    result = subprocess.run(
        ["uv", "run", "python", test_file],
        cwd=r"D:\own_project\qgis-agentv2",
        capture_output=False,
        text=True
    )
    
    return result.returncode == 0

def main():
    """主函数"""
    print("\n" + "="*60)
    print("QGIS Agent - 完整测试套件")
    print("="*60)
    
    tests = [
        (r".\tests\test_graph.py", "Graph构建测试"),
        (r".\tests\test_planner_node.py", "Planner Node测试"),
        (r".\tests\test_api_rag_node.py", "API RAG Node测试"),
        (r".\tests\test_reflector_node.py", "Reflector Node测试"),
        (r".\tests\test_optimizations.py", "优化功能测试"),
        (r".\tests\test_e2e_graph.py", "端到端集成测试"),
    ]
    
    results = {}
    
    for test_file, description in tests:
        success = run_test(test_file, description)
        results[description] = "✅ 通过" if success else "❌ 失败"
    
    # 显示测试结果汇总
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    
    for test_name, result in results.items():
        print(f"{result} - {test_name}")
    
    # 统计
    passed = sum(1 for r in results.values() if "✅" in r)
    total = len(results)
    
    print("\n" + "="*60)
    print(f"总计: {passed}/{total} 测试通过")
    print("="*60 + "\n")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
