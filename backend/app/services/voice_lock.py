"""Single active voice-call guard (free-tier hard limit: one call at a time).

1. Redis lock ``voice:call:active`` = room name (SET NX, 2-min TTL).
   Released on explicit hangup; TTL covers crashes.
2. LiveKit ground truth: only the locked room is checked for participants.
"""

from __future__ import annotations

import asyncio
import logging

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

VOICE_LOCK_KEY = "voice:call:active"
VOICE_LOCK_TTL_SECONDS = 2 * 60

_client: redis.Redis | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


async def _redis() -> redis.Redis | None:
    global _client, _client_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    if _client is not None and _client_loop is not loop:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None
        _client_loop = None
    if _client is not None:
        return _client
    try:
        client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        await client.ping()
        _client = client
        _client_loop = loop
        return _client
    except Exception:
        logger.warning("voice lock: redis unavailable, using LiveKit check only")
        return None


async def _current_locked_room() -> str | None:
    client = await _redis()
    if client is None:
        return None
    try:
        return await client.get(VOICE_LOCK_KEY)
    except Exception:
        return None


async def livekit_room_busy(room: str | None = None) -> bool:
    """True if the locked room currently has participants."""
    import os

    # NOTE: os.environ (not Settings) — Settings has no livekit fields and
    # extra="ignore" drops them, which 500s every token call (verified
    # locally). Gateway reads the same vars from os.environ.
    lk_url = os.environ.get("LIVEKIT_URL", "")
    lk_key = os.environ.get("LIVEKIT_API_KEY", "")
    lk_secret = os.environ.get("LIVEKIT_API_SECRET", "")
    if not lk_url or not lk_key or not lk_secret:
        return False
    try:
        from livekit.api import LiveKitAPI, ListParticipantsRequest

        async with LiveKitAPI(lk_url, lk_key, lk_secret) as api:
            target = room or await _current_locked_room()
            if not target:
                return False
            ps = await api.room.list_participants(ListParticipantsRequest(room=target))
            return len(ps.participants) > 0
    except Exception:
        logger.warning("voice lock: LiveKit check failed", exc_info=True)
        return False


async def acquire_voice_call(room: str) -> tuple[bool, str]:
    """Try to claim the single voice slot for `room`.

    Returns (acquired, reason): reason is "ok", "busy" or "stale-stolen".

    LiveKit is checked first so a live room always blocks, even if the
    Redis lock expired or was never set (hard single-call guarantee).
    """
    if await livekit_room_busy():
        return False, "busy"
    client = await _redis()
    if client is not None:
        try:
            taken = await client.set(VOICE_LOCK_KEY, room, nx=True, ex=VOICE_LOCK_TTL_SECONDS)
            if taken:
                return True, "ok"
            current = await client.get(VOICE_LOCK_KEY)
            if current and not await livekit_room_busy(current):
                await client.set(VOICE_LOCK_KEY, room, ex=VOICE_LOCK_TTL_SECONDS)
                logger.info("voice lock: stole stale lock for finished room")
                return True, "stale-stolen"
            return False, "busy"
        except Exception:
            logger.warning("voice lock: redis error on acquire", exc_info=True)

    if await livekit_room_busy(room):
        return False, "busy"
    return True, "ok"


async def release_voice_call(room: str) -> bool:
    """Release the slot if it is held by `room`. Never raises."""
    try:
        client = await _redis()
        if client is None:
            return False
        current = await client.get(VOICE_LOCK_KEY)
        if current == room:
            await client.delete(VOICE_LOCK_KEY)
            return True
        return False
    except Exception:
        logger.warning("voice lock: redis error on release", exc_info=True)
        return False
