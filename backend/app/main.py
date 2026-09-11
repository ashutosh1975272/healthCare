from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import AppError, app_error_handler, db_error_handler
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import engine
from sqlalchemy.exc import SQLAlchemyError


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    yield


configure_logging()

app = FastAPI(title="Aarogya API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://health-care-xi-rust.vercel.app",
        "https://aarogya-health-ak123456789.duckdns.org:20354",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.add_middleware(RequestContextMiddleware)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(SQLAlchemyError, db_error_handler)
app.include_router(api_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return {"status": "degraded", "database": "unavailable"}
    return {"status": "ready"}
