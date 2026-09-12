"""Per-user Groq API key loader for the LiveKit voice worker.

Standalone module: must NOT import anything from ``backend/app`` so the
worker stays decoupled from the FastAPI application. It opens its own
short-lived SQLAlchemy async engine from ``database_url``, reads the
user's active Groq key row, and Fernet-decrypts it exactly like
``app.services.api_key_service._get_fernet`` (SHA256 of the secret key).

The raw key is never logged — only found/missing keyed by user_id.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid

logger = logging.getLogger(__name__)


def _get_fernet(secret_key: str):
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(secret_key.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def _normalize_url(database_url: str) -> str:
    """Ensure an async driver is present (mirrors backend/app usage).

    ``backend/app`` expects ``postgresql+asyncpg://...``. Plain
    ``postgresql://`` URLs (e.g. from env) get the ``+asyncpg`` driver
    swapped in so ``create_async_engine`` works.
    """
    if database_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + database_url[len("postgresql://") :]
    return database_url


async def load_user_key(
    database_url: str, secret_key: str, user_id: str, provider: str
) -> tuple[str | None, str]:
    """Load and decrypt a user's active key for any provider.

    Returns (raw_key_or_None, source) where source is one of
    "db" | "env" | "none". Env fallback mirrors
    ``app.ai.gateway._get_key`` so voice keeps working when the user
    has no personal key but the server has a shared one.
    """
    import os

    key = await _load_db_key(database_url, secret_key, user_id, provider)
    if key:
        return key, "db"
    env_map = {
        "groq": ["GROQ_API_KEY"],
        "nvidia": ["NVIDIA_API_KEY", "LLM_API_KEY"],
    }
    for var in env_map.get(provider, []):
        val = os.environ.get(var, "")
        if val:
            logger.info("%s key from server env for user_id=%s", provider, user_id)
            return val, "env"
    logger.info("%s key missing for user_id=%s", provider, user_id)
    return None, "none"


async def load_user_groq_key(database_url: str, secret_key: str, user_id: str) -> str | None:
    """Backward-compat wrapper: user Groq key, else shared server env key."""
    key, _ = await load_user_key(database_url, secret_key, user_id, "groq")
    return key


async def load_voice_keys(
    database_url: str, secret_key: str, user_id: str
) -> dict[str, tuple[str | None, str]]:
    """Load Groq + NVIDIA keys for a voice session (each as (key, source))."""
    groq = await load_user_key(database_url, secret_key, user_id, "groq")
    nvidia = await load_user_key(database_url, secret_key, user_id, "nvidia")
    return {"groq": groq, "nvidia": nvidia}


async def _load_db_key(
    database_url: str, secret_key: str, user_id: str, provider: str
) -> str | None:
    if provider not in ("groq", "nvidia"):
        return None
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, AttributeError, TypeError):
        logger.warning("%s key lookup: invalid user_id=%s", provider, user_id)
        return None

    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(_normalize_url(database_url), pool_pre_ping=True)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT api_key_encrypted FROM api_keys "
                        "WHERE user_id = :user_id AND provider = :provider "
                        "AND is_active = true LIMIT 1"
                    ),
                    {"user_id": uid, "provider": provider},
                )
                row = result.first()
        finally:
            await engine.dispose()

        if row is None or not row[0]:
            logger.info("%s key missing in db for user_id=%s", provider, user_id)
            return None

        try:
            raw = _get_fernet(secret_key).decrypt(row[0].encode()).decode()
        except Exception:
            logger.warning("%s key decrypt failed for user_id=%s", provider, user_id)
            return None

        if not raw:
            logger.info("%s key missing in db for user_id=%s", provider, user_id)
            return None
        logger.info("%s key found in db for user_id=%s", provider, user_id)
        return raw
    except Exception:
        logger.warning("%s key lookup failed for user_id=%s", provider, user_id)
        return None
