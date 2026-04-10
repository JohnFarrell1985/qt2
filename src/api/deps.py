"""FastAPI 共享依赖 — 统一类型注解, 避免各 router 重复导入"""
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from src.common.db import get_db

SessionDep = Annotated[Session, Depends(get_db)]
