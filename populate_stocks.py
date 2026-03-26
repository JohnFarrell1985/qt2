#!/usr/bin/env python3
"""
批量填充stocks表 - 从离线数据文件提取股票代码和名称
"""
import os
import pandas as pd
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# 数据库连接
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def extract_name_from_csv(file_path: Path) -> tuple:
    """从CSV文件提取股票代码和名称"""
    try:
        df = pd.read_csv(file_path, nrows=1)  # 只读第一行
        
        # 尝试从列名或数据中提取
        code = None
        name = None
        
        # 从文件名提取代码
        stem = file_path.stem
        if '_SZ' in stem or '_SH' in stem or '_BJ' in stem:
            code = stem.split('_')[0]
        
        # 从stock_code列提取名称（如果有）
        if 'stock_code' in df.columns:
            stock_code_full = str(df['stock_code'].iloc[0])
            # 000001.SZ -> 提取名称需要从其他来源
            
        return code, name
    except Exception as e:
        print(f"读取失败 {file_path}: {e}")
        return None, None

def populate_stocks_from_files(data_dir: str):
    """从CSV文件填充stocks表"""
    daily_dir = Path(data_dir) / 'a_stock_daily'
    
    if not daily_dir.exists():
        print(f"目录不存在: {daily_dir}")
        return
    
    csv_files = list(daily_dir.glob('*.csv'))
    print(f"找到 {len(csv_files)} 个CSV文件")
    
    # 准备数据
    stock_records = []
    for file_path in csv_files:
        stem = file_path.stem
        if '_SZ' in stem:
            code = stem.replace('_SZ', '')
            exchange = 'SZ'
        elif '_SH' in stem:
            code = stem.replace('_SH', '')
            exchange = 'SH'
        elif '_BJ' in stem:
            code = stem.replace('_BJ', '')
            exchange = 'BJ'
        else:
            continue
            
        # 临时名称，后续可以更新
        name = f"股票{code}"
        
        stock_records.append({
            'code': code,
            'name': name,
            'exchange': exchange
        })
    
    print(f"准备插入 {len(stock_records)} 条记录")
    
    # 批量插入（UPSERT）
    with SessionLocal() as session:
        inserted = 0
        updated = 0
        
        for record in stock_records:
            # 检查是否已存在
            existing = session.execute(
                text("SELECT code FROM stocks WHERE code = :code"),
                {'code': record['code']}
            ).first()
            
            if existing:
                # 更新（如果名称为空或是临时名称）
                session.execute(
                    text("""
                        UPDATE stocks 
                        SET exchange = :exchange,
                            name = CASE WHEN name IS NULL OR name LIKE '股票%' THEN :name ELSE name END
                        WHERE code = :code
                    """),
                    record
                )
                updated += 1
            else:
                # 插入新记录
                session.execute(
                    text("""
                        INSERT INTO stocks (code, name, exchange)
                        VALUES (:code, :name, :exchange)
                    """),
                    record
                )
                inserted += 1
        
        session.commit()
        print(f"✅ 完成: 插入 {inserted} 条, 更新 {updated} 条")

def update_stock_names_from_daily():
    """从stock_daily表的已有数据更新stocks表"""
    with SessionLocal() as session:
        # 获取stock_daily中所有唯一的code
        result = session.execute(text("""
            SELECT DISTINCT code FROM stock_daily
            WHERE code NOT IN (SELECT code FROM stocks)
        """))
        
        missing_codes = [row.code for row in result]
        print(f"stock_daily中有 {len(missing_codes)} 只股票不在stocks表中")
        
        # 插入缺失的记录
        inserted = 0
        for code in missing_codes:
            # 判断交易所
            if code.startswith('6'):
                exchange = 'SH'
            elif code.startswith('0') or code.startswith('3'):
                exchange = 'SZ'
            elif code.startswith('4') or code.startswith('8'):
                exchange = 'BJ'
            else:
                exchange = 'OTHER'
            
            session.execute(
                text("""
                    INSERT INTO stocks (code, name, exchange)
                    VALUES (:code, :name, :exchange)
                """),
                {'code': code, 'name': f'股票{code}', 'exchange': exchange}
            )
            inserted += 1
            
            if inserted % 100 == 0:
                session.commit()
                print(f"  已插入 {inserted} 条...")
        
        session.commit()
        print(f"✅ 完成: 插入 {inserted} 条记录到stocks表")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--from-daily':
        # 从stock_daily表更新
        print("从stock_daily表更新stocks表...")
        update_stock_names_from_daily()
    else:
        # 从CSV文件填充（需要提供数据目录）
        data_dir = sys.argv[1] if len(sys.argv) > 1 else "/app/offline_data"
        print(f"从CSV文件填充stocks表: {data_dir}")
        populate_stocks_from_files(data_dir)
