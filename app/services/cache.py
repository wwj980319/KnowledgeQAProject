import hashlib
import json

import redis

from app.config import settings

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def cache_key(user_id: int, question: str) -> str:
    normalized = question.strip().lower()
    return f"qa:cache:{user_id}:" + hashlib.sha256(normalized.encode()).hexdigest()


def get_cached_answer(user_id: int, question: str) -> dict | None:
    raw = get_redis().get(cache_key(user_id, question))
    return json.loads(raw) if raw else None


def set_cached_answer(user_id: int, question: str, payload: dict) -> None:
    get_redis().set(
        cache_key(user_id, question),
        json.dumps(payload, ensure_ascii=False),
        ex=settings.cache_ttl_seconds,
    )
