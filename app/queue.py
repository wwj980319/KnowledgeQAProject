import redis
from rq import Queue

from app.config import settings


def get_queue() -> Queue:
    return Queue("documents", connection=redis.from_url(settings.redis_url))
