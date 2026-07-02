"""Token endpoint — generates LiveKit access tokens and creates rooms for browser WebRTC."""

import asyncio
import time
from collections import defaultdict, deque
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from livekit.api import AccessToken, LiveKitAPI, VideoGrants

from app.config import get_settings

router = APIRouter()
logger = structlog.get_logger(__name__)

# Cost guard: each /token creates a real LiveKit room + dispatches a worker + Airtable write.
# ponytail: in-process, per-worker limiter (resets on restart, doesn't share across uvicorn
# workers). Move to Redis only if this runs multi-worker and abuse gets past it.
_RATE_LIMIT = 5           # max requests per IP per window
_RATE_WINDOW = 60         # seconds
_MAX_CONCURRENT_ROOMS = 3

_hits: dict[str, deque] = defaultdict(deque)
_room_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_ROOMS)


def _client_ip(request: Request) -> str:
    # ponytail: trusts the left-most X-Forwarded-For (nginx sets it). Spoofable by rotating
    # the header — the concurrency cap is the backstop against total amplification.
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    hits = _hits[ip]
    while hits and now - hits[0] > _RATE_WINDOW:
        hits.popleft()
    if len(hits) >= _RATE_LIMIT:
        return True
    hits.append(now)
    return False


@router.post("/token")
async def create_token(request: Request) -> JSONResponse:
    """Generate a LiveKit access token and create a room for browser click-to-talk."""
    ip = _client_ip(request)
    if _rate_limited(ip):
        logger.warning("token.rate_limited", ip=ip)
        raise HTTPException(status_code=429, detail="Too many requests, please slow down.")

    settings = get_settings()

    room_name = f"aura-web-{uuid4().hex[:8]}"
    identity = f"web-user-{uuid4().hex[:6]}"

    # Create the room via server API so the agent worker gets dispatched
    async with _room_semaphore:  # bound concurrent room creation across all callers
        api = LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )

        try:
            from livekit.api import CreateRoomRequest
            await api.room.create_room(CreateRoomRequest(name=room_name))
            logger.info("token.room_created", room=room_name)
        except Exception as e:
            logger.error("token.room_creation_failed", error=str(e), room=room_name)
        finally:
            await api.aclose()

    # Generate access token for the browser participant (v1.x builder API)
    token = (
        AccessToken(
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        .with_identity(identity)
        .with_name("Web Visitor")
        .with_grants(VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
        ))
    )

    jwt_token = token.to_jwt()

    logger.info(
        "token.created",
        room=room_name,
        identity=identity,
    )

    return JSONResponse(
        content={
            "token": jwt_token,
            "room": room_name,
            "url": settings.livekit_url,
        }
    )
