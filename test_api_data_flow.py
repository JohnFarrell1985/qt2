#!/usr/bin/env python3
"""
测试 api-middleware 数据流 - 验证数据是否正确注入提示词
"""
import requests
import json
import sys

API_URL = "http://localhost:8012"

def test_health():
    """测试健康检查"""
    print("="*60)
    print("1. 测试健康检查")
    print("="*60)
    try:
        r = requests.get(f"{API_URL}/health", timeout=5)
        data = r.json()
        print(f"✅ API状态: {data['status']}")
        print(f"   数据库: {data.get('database', {})}")
        return True
    except Exception as e:
        print(f"❌ 失败: {e}")
        return False

def test_intent_recognition():
    """测试意图识别 - 关键测试"""
    print("\n" + "="*60)
    print("2. 测试意图识别（关键）")
    print("="*60)
    
    test_cases = [
        "分析000001",
        "平安银行最近走势",
        "查看600519的历史数据"
    ]
    
    for msg in test_cases:
        print(f"\n测试: '{msg}'")
        try:
            r = requests.post(
                f"{API_URL}/v1/chat/completions",
                json={
                    "model": "Fin-R1-Live",
                    "messages": [{"role": "user", "content": msg}],
                    "stream": False
                },
                timeout=30
            )
            
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            
            # 检查关键标记
            has_data_marker = "【历史数据统计" in content or "【实时行情" in content
            has_warning = "⚠️" in content and "暂无数据" in content
            
            print(f"  返回内容长度: {len(content)}")
            print(f"  包含数据标记: {has_data_marker}")
            print(f"  包含无数据警告: {has_warning}")
            
            # 显示前500字符
            preview = content[:500].replace('\n', ' ')
            print(f"  预览: {preview}...")
            
        except Exception as e:
            print(f"  ❌ 失败: {e}")

def test_database_direct():
    """直接测试数据库查询"""
    print("\n" + "="*60)
    print("3. 直接测试数据库查询")
    print("="*60)
    
    # 使用 api-middleware 的 /api/stock/{code}/history 端点
    try:
        r = requests.get(f"{API_URL}/api/stock/000001/history?days=5", timeout=10)
        if r.status_code == 200:
            data = r.json()
            print(f"✅ 直接查询成功")
            print(f"   返回数据条数: {len(data) if isinstance(data, list) else 'N/A'}")
            if isinstance(data, list) and len(data) > 0:
                print(f"   样本: {data[0]}")
        else:
            print(f"❌ 查询失败: HTTP {r.status_code}")
    except Exception as e:
        print(f"❌ 失败: {e}")

def test_system_prompt_content():
    """测试系统提示词内容（最严格测试）"""
    print("\n" + "="*60)
    print("4. 测试系统提示词内容（最严格）")
    print("="*60)
    
    try:
        r = requests.post(
            f"{API_URL}/v1/chat/completions",
            json={
                "model": "Fin-R1-Live",
                "messages": [{"role": "user", "content": "000001"}],
                "stream": False
            },
            timeout=30
        )
        
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        
        # 严格检查
        checks = {
            "【重要：你必须基于以下提供的数据进行分析】": "【重要：你必须基于" in content,
            "【历史数据统计": "【历史数据统计" in content,
            "【实时行情": "【实时行情" in content,
            "【禁止事项】": "【禁止事项】" in content,
            "禁止使用假设数据": "禁止使用假设数据" in content,
            "PostgreSQL数据库": "PostgreSQL数据库" in content,
        }
        
        print("\n提示词元素检查:")
        all_pass = True
        for element, found in checks.items():
            status = "✅" if found else "❌"
            print(f"  {status} {element[:40]}...")
            if not found:
                all_pass = False
        
        # 检查是否有"假设"、"模拟"等关键词（不应该出现）
        forbidden = ["假设我能", "模拟数据", "假设数据", "无法直接访问"]
        found_forbidden = [f for f in forbidden if f in content]
        
        if found_forbidden:
            print(f"\n⚠️ 发现禁用词汇: {found_forbidden}")
        else:
            print(f"\n✅ 未发现禁用词汇")
        
        # 如果所有检查都失败，打印完整内容
        if not all_pass and not any(checks.values()):
            print(f"\n❌ 所有检查都失败！完整返回内容（前1500字符）:")
            print(content[:1500])
            
    except Exception as e:
        print(f"❌ 失败: {e}")

if __name__ == "__main__":
    print("Fin-R1 API Middleware 数据流诊断工具")
    print("="*60)
    
    # 运行所有测试
    if test_health():
        test_intent_recognition()
        test_database_direct()
        test_system_prompt_content()
    
    print("\n" + "="*60)
    print("诊断完成")
    print("="*60)
    print("\n分析:")
    print("- 如果'意图识别'中'包含数据标记'为False，说明数据查询返回空")
    print("- 如果'系统提示词内容'检查都失败，说明提示词构建有问题")
    print("- 如果'直接测试数据库查询'成功但意图识别失败，说明代码逻辑有问题")
