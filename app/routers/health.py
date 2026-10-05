from fastapi import APIRouter
from sqlalchemy import text

from app.database import engine
from app.services.cache import get_redis

router = APIRouter(tags=["ops"])


@router.get("/health")
def health():
    pg_ok = redis_ok = False
    try:
        # 不走 get_db 依赖：PG 完全不可达时依赖注入阶段就会抛错，绕过本函数的
        # try/except 变成 500；直连 engine 才能保证任何故障都落在守卫内返回 degraded
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        pg_ok = True
    except Exception:
        pass
    try:
        redis_ok = bool(get_redis().ping())
    except Exception:
        pass
    return {
        "status": "ok" if (pg_ok and redis_ok) else "degraded",
        "postgres": pg_ok,
        "redis": redis_ok,
    }
