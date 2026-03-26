#!/usr/bin/env python3
"""
抓取全部A股股票代码和名称（完整版 - 5000+只）
使用东方财富分页接口，确保抓取全部
"""
import requests
import csv
import time
import json

def fetch_all_stocks_from_eastmoney():
    """
    从东方财富获取全部A股列表（完整版）
    使用分页接口，确保获取全部5000+只股票
    """
    print("="*60)
    print("从东方财富获取全部A股列表")
    print("="*60)
    
    all_stocks = []
    page = 1
    max_pages = 20  # 最多20页，每页500只
    
    while page <= max_pages:
        # 东方财富接口参数说明：
        # pn: 页码, pz: 每页数量
        # fs: 股票范围（m:0=深圳, m:1=上海）
        # fields: f12=代码, f14=名称
        url = (
            f"http://81.push2.eastmoney.com/api/qt/clist/get"
            f"?pn={page}&pz=500&po=1&np=1&fltt=2&invt=2"
            f"&fid=f12"
            f"&fs=m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23,m:1+t:81"
            f"&fields=f12,f14"
        )
        
        try:
            response = requests.get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            if response.status_code != 200:
                print(f"  第{page}页请求失败: HTTP {response.status_code}")
                break
            
            data = response.json()
            
            # 检查返回数据格式
            if not data.get('data') or not data['data'].get('diff'):
                print(f"  第{page}页无数据")
                break
            
            stocks = data['data']['diff']
            if not stocks:
                print(f"  第{page}页为空")
                break
            
            # 解析当前页数据
            page_count = 0
            for stock in stocks:
                code = stock.get('f12')
                name = stock.get('f14')
                
                if code and name and len(code) == 6:
                    # 判断交易所
                    if code.startswith('6'):
                        exchange = 'SH'
                    elif code.startswith('0') or code.startswith('3'):
                        exchange = 'SZ'
                    elif code.startswith('4') or code.startswith('8'):
                        exchange = 'BJ'
                    else:
                        exchange = 'OTHER'
                    
                    all_stocks.append({
                        'code': code,
                        'name': name,
                        'exchange': exchange
                    })
                    page_count += 1
            
            print(f"  第{page:2d}页: {page_count:3d} 只 (累计: {len(all_stocks):4d})")
            
            # 如果本页不足500只，说明是最后一页
            if len(stocks) < 500:
                print(f"  到达最后一页")
                break
            
            page += 1
            time.sleep(0.3)  # 防止请求过快
            
        except Exception as e:
            print(f"  第{page}页异常: {e}")
            break
    
    return all_stocks

def verify_completeness(stocks):
    """验证数据完整性"""
    print("\n" + "="*60)
    print("数据完整性验证")
    print("="*60)
    
    if len(stocks) == 0:
        print("❌ 未获取到任何数据")
        return False
    
    # 按交易所统计
    sh_count = sum(1 for s in stocks if s['exchange'] == 'SH')
    sz_count = sum(1 for s in stocks if s['exchange'] == 'SZ')
    bj_count = sum(1 for s in stocks if s['exchange'] == 'BJ')
    other_count = sum(1 for s in stocks if s['exchange'] == 'OTHER')
    
    print(f"总计: {len(stocks)} 只股票")
    print(f"  上海(SH): {sh_count:4d} 只")
    print(f"  深圳(SZ): {sz_count:4d} 只")
    print(f"  北京(BJ): {bj_count:4d} 只")
    print(f"  其他:     {other_count:4d} 只")
    
    # 检查是否完整（通常A股总数在5000-5500之间）
    if len(stocks) >= 5000:
        print(f"✅ 数据完整: 获取到 {len(stocks)} 只，符合A股总数")
        return True
    elif len(stocks) >= 4000:
        print(f"⚠️ 数据可能不完整: 仅获取到 {len(stocks)} 只，预期 5000+")
        return True  # 仍然保存，但警告
    else:
        print(f"❌ 数据严重不足: 仅获取到 {len(stocks)} 只，预期 5000+")
        return False

def save_to_csv(stocks, filename="stock_names_complete.csv"):
    """保存到CSV文件"""
    print("\n" + "="*60)
    print("保存到CSV文件")
    print("="*60)
    
    # 按代码排序
    stocks_sorted = sorted(stocks, key=lambda x: x['code'])
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['code', 'name', 'exchange'])
        writer.writeheader()
        writer.writerows(stocks_sorted)
    
    import os
    filepath = os.path.abspath(filename)
    filesize = os.path.getsize(filename)
    
    print(f"✅ 保存成功")
    print(f"  文件路径: {filepath}")
    print(f"  文件大小: {filesize:,} 字节")
    print(f"  股票数量: {len(stocks_sorted):,} 只")
    
    # 显示前10条作为示例
    print(f"\n前10条记录:")
    for i, s in enumerate(stocks_sorted[:10], 1):
        print(f"  {i}. {s['code']} | {s['name']:8s} | {s['exchange']}")

def main():
    print("\n" + "="*60)
    print("A股全量股票抓取工具")
    print("目标: 获取全部5000+只A股代码和名称")
    print("="*60 + "\n")
    
    # 抓取数据
    stocks = fetch_all_stocks_from_eastmoney()
    
    # 验证完整性
    is_complete = verify_completeness(stocks)
    
    if len(stocks) > 0:
        # 保存到CSV
        save_to_csv(stocks)
        
        print("\n" + "="*60)
        print("抓取完成！")
        print("="*60)
        print(f"\n下一步:")
        print(f"1. 将 stock_names_complete.csv 上传到服务器")
        print(f"2. 执行: docker cp stock_names_complete.csv finr1-datahub:/app/stock_names.csv")
        print(f"3. 执行: docker exec finr1-datahub python update_stock_names_csv.py")
        
        if not is_complete:
            print(f"\n⚠️ 警告: 数据可能不完整，建议重新运行脚本")
    else:
        print("\n❌ 抓取失败，请检查网络连接或更换数据源")

if __name__ == "__main__":
    main()
