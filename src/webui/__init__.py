"""模拟盘交易 Web UI (FastAPI)

本地运行的自包含模拟盘 (paper trading) 交易终端, 电脑端与手机端浏览器均可访问。
界面参考同花顺远航版交易终端 (交易页, 非行情页), 红涨绿跌。

启动:
    python -m src.webui            # 默认 0.0.0.0:8001
    python -m src.webui --port 8001 --host 0.0.0.0
"""
