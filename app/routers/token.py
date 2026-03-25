"""Token endpoint — generates LiveKit access tokens and creates rooms for browser WebRTC."""

from uuid import uuid4

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from livekit.api import AccessToken, LiveKitAPI, VideoGrants

from app.config import get_settings

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.post("/token")
async def create_token() -> JSONResponse:
    """Generate a LiveKit access token and create a room for browser click-to-talk."""
    settings = get_settings()

    room_name = f"aura-web-{uuid4().hex[:8]}"
    identity = f"web-user-{uuid4().hex[:6]}"

    # Create the room via server API so the agent worker gets dispatched
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
