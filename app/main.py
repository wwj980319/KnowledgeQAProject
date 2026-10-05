import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.database import init_db
from app.logging_conf import setup_logging
from app.routers import auth as auth_router
from app.routers import documents as documents_router
from app.routers import health as health_router
from app.routers import query as query_router

logger = logging.getLogger("request")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    yield


app = FastAPI(title="Knowledge QA Service", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    logger.info(
        "request",
        extra={
            "path": f"{request.method} {request.url.path}",
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1),
        },
    )
    return response


app.include_router(auth_router.router)
app.include_router(documents_router.router)
app.include_router(query_router.router)
app.include_router(health_router.router)
