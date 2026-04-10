"""Create qt_quant database if it doesn't exist."""
from sqlalchemy import create_engine, text

engine = create_engine(
    "postgresql://game_agents:1234+asdf@123.60.11.74:5432/postgres",
    isolation_level="AUTOCOMMIT",
)
with engine.connect() as conn:
    result = conn.execute(
        text("SELECT datname FROM pg_database WHERE datname='qt_quant'")
    )
    exists = result.fetchone()
    if not exists:
        conn.execute(text("CREATE DATABASE qt_quant"))
        print("Database qt_quant created")
    else:
        print("Database qt_quant already exists")

engine.dispose()
