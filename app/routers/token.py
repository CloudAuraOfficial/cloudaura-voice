"""Token endpoint — generates LiveKit access tokens for browser-based WebRTC connections."""

from uuid import uuid4

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from livekit.api import AccessToken, VideoGrants

from app.config import get_settings

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.post("/token")
async def create_token() -> JSONResponse:
    """Generate a LiveKit access token for a browser participant."""
    settings = get_settings()

    room_name = f"aura-web-{uuid4().hex[:8]}"
    identity = f"web-user-{uuid4().hex[:6]}"

    token = AccessToken(
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    token.identity = identity
    token.name = "Web Visitor"

    grant = VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
    )
    token.video_grants = grant

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
