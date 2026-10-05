import time

from fastapi import HTTPException

from app.config import settings
from app.services.cache import get_redis


def check_rate_limit(user_id: int) -> None:
    window = int(time.time()) // 60
    key = f"rl:{user_id}:{window}"
    r = get_redis()
    count = r.incr(key)
    if count == 1:
        r.expire(key, 60)
    if count > settings.rate_limit_per_minute:
        raise HTTPException(429, "Rate limit exceeded, try again later")
