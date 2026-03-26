#!/usr/bin/env python3
"""
数据流程诊断脚本 - 检查数据是否正常流动到API
"""
import requests
import json
import psycopg2

# 配置
DB_URL = "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data"
API_URL = "http://localhost:8012"

def test_database():
    """测试数据库连接和数据"""
    print("="*60)
    print("1. 测试数据库连接和数据")
    print("="*60)
    
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        # 检查stock_daily表
        cur.execute("""
            SELECT 
                COUNT(*) as total_records,
                COUNT(DISTINCT code) as stock_count,
                MIN(trade_date) as min_date,
                MAX(trade_date) as max_date
            FROM stock_daily
        """)
        result = cur.fetchone()
        print(f"✅ stock_daily表:")
        print(f"   总记录数: {result[0]:,}")
        print(f"   股票数量: {result[1]:,}")
        print(f"   日期范围: {result[2]} ~ {result[3]}")
        
        # 检查000001的数据
        cur.execute("""
            SELECT trade_date, close, volume 
            FROM stock_daily 
            WHERE code = '000001' 
            ORDER BY trade_date DESC 
            LIMIT 5
        """)
        rows = cur.fetchall()
        if rows:
            print(f"\n✅ 000001(平安银行) 最近5条数据:")
            for row in rows:
                print(f"   {row[0]}: 收盘价¥{row[1]}, 成交量{row[2]:,}")
        else:
            print(f"\n❌ 000001 无数据!")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        return False

def test_api_health():
    """测试API健康状态"""
    print("\n" + "="*60)
    print("2. 测试API健康状态")
    print("="*60)
    
    try:
        response = requests.get(f"{API_URL}/health", timeout=10)
        data = response.json()
        print(f"✅ API状态: {data['status']}")
        print(f"   数据库连接: {data['database']}")
        return True
    except Exception as e:
        print(f"❌ API连接失败: {e}")
        return False

def test_api_data_injection():
    """测试API是否正确注入数据到提示词"""
    print("\n" + "="*60)
    print("3. 测试API数据注入")
    print("="*60)
    
    try:
        response = requests.post(
            f"{API_URL}/v1/chat/completions",
            json={
                "model": "Fin-R1-Live",
                "messages": [{"role": "user", "content": "分析000001"}],
                "stream": False
            },
            timeout=30
        )
        
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        
        # 检查是否包含数据标记
        if "【历史数据统计" in content or "【实时行情" in content:
            print("✅ API已注入数据到提示词")
            print("\n提示词开头部分:")
            print(content[:500])
        else:
            print("❌ 提示词中未找到数据标记!")
            print("\n实际返回内容开头:")
            print(content[:500])
        
        # 检查是否包含禁止词
        forbidden_words = ["假设", "模拟", "无法访问"]
        for word in forbidden_words:
            if word in content:
                print(f"\n⚠️ 警告: 提示词中包含禁止词 '{word}'")
        
        return True
        
    except Exception as e:
        print(f"❌ API调用失败: {e}")
        return False

def test_vllm_response():
    """测试完整流程 - 查看vLLM返回"""
    print("\n" + "="*60)
    print("4. 测试vLLM响应（完整流程）")
    print("="*60)
    
    try:
        response = requests.post(
            f"{API_URL}/v1/chat/completions",
            json={
                "model": "Fin-R1-Live",
                "messages": [{"role": "user", "content": "平安银行000001今天的股价是多少？请基于提供的数据回答，不要假设。"}],
                "stream": False,
                "temperature": 0.1  # 降低随机性
            },
            timeout=60
        )
        
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        
        print("vLLM响应:")
        print(content[:1000])
        
        # 检查是否基于真实数据
        if "假设" in content or "模拟" in content:
            print("\n❌ AI仍然在假设数据!")
        elif "¥" in content or "元" in content or "收盘价" in content:
            print("\n✅ AI似乎在使用具体数据")
        else:
            print("\n⚠️ 无法确定AI是否使用了真实数据")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")

if __name__ == "__main__":
    print("Fin-R1 数据流程诊断工具")
    print("="*60)
    
    # 运行所有测试
    db_ok = test_database()
    api_ok = test_api_health()
    
    if db_ok and api_ok:
        test_api_data_injection()
        test_vllm_response()
    else:
        print("\n❌ 基础测试失败，请先修复数据库或API连接问题")
    
    print("\n" + "="*60)
    print("诊断完成")
    print("="*60)
