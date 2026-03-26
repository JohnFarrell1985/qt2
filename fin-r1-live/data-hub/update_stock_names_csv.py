#!/usr/bin/env python3
"""
更新stocks表的股票名称 - 从CSV文件读取（离线方案）
CSV格式: code,name,exchange (如: 000001,平安银行,SZ)
"""
import os
import sys
import csv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def update_from_csv(csv_path: str):
    """从CSV文件更新股票名称"""
    if not os.path.exists(csv_path):
        print(f"❌ CSV文件不存在: {csv_path}")
        return
    
    print(f"正在读取CSV: {csv_path}")
    
    stock_data = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get('code', '').strip()
            name = row.get('name', '').strip()
            exchange = row.get('exchange', '').strip()
            
            if code and name:
                stock_data.append({
                    'code': code,
                    'name': name,
                    'exchange': exchange or 'UNKNOWN'
                })
    
    print(f"读取到 {len(stock_data)} 条记录")
    
    # 更新到数据库
    with SessionLocal() as session:
        updated = 0
        
        for record in stock_data:
            existing = session.execute(
                text("SELECT code FROM stocks WHERE code = :code"),
                {'code': record['code']}
            ).first()
            
            if existing:
                session.execute(
                    text("UPDATE stocks SET name = :name, exchange = :exchange WHERE code = :code"),
                    record
                )
                updated += 1
            else:
                session.execute(
                    text("INSERT INTO stocks (code, name, exchange) VALUES (:code, :name, :exchange)"),
                    record
                )
        
        session.commit()
        
    print(f"✅ 完成: 更新了 {updated} 条，插入了 {len(stock_data) - updated} 条")

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "/app/stock_names.csv"
    update_from_csv(csv_path)
