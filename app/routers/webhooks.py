from typing import Optional

import structlog
from fastapi import APIRouter, Form, Request, Response

from app.models.schemas import ResolutionStatus
from app.services.airtable_service import AirtableService
from app.services.twilio_service import TwilioService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _twilio() -> TwilioService:
    return TwilioService()


def _airtable() -> AirtableService:
    return AirtableService()


@router.post("/twilio/voice")
async def twilio_voice(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    CallStatus: str = Form(...),
) -> Response:
    """
    Twilio inbound voice webhook.
    Builds a LiveKit room name from the CallSid and returns TwiML
    that routes the call into that room via SIP.
    """
    log = logger.bind(call_sid=CallSid, caller=From, status=CallStatus)

    # Sanitise caller number for inclusion in the room name (no '+' allowed in SIP URI path)
    safe_caller = From.replace("+", "-").replace(" ", "")
    room_name = f"call_{CallSid}_{safe_caller}"

    log.info("twilio.inbound_call", room_name=room_name)

    twilio = _twilio()
    try:
        twiml = twilio.build_sip_response(room_name)
    except Exception as exc:
        log.error("twilio.voice_webhook_error", error=str(exc))
        twiml = twilio.build_error_response(
            "We're sorry, the assistant is temporarily unavailable. Please try again shortly."
        )

    return Response(content=twiml, media_type="application/xml")


@router.post("/twilio/status")
async def twilio_status(
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: Optional[str] = Form(None),
    From: str = Form(...),
    To: str = Form(...),
) -> Response:
    """
    Twilio status callback — fired on every call state transition.
    On terminal states, updates the Airtable record with duration and outcome.
    """
    log = logger.bind(call_sid=CallSid, status=CallStatus, duration=CallDuration)
    log.info("twilio.status_callback")

    terminal_states = {"completed", "failed", "no-answer", "busy", "canceled"}
    if CallStatus in terminal_states:
        status_to_resolution = {
            "completed": ResolutionStatus.RESOLVED,
            "failed": ResolutionStatus.DROPPED,
            "no-answer": ResolutionStatus.DROPPED,
            "busy": ResolutionStatus.DROPPED,
            "canceled": ResolutionStatus.DROPPED,
        }
        airtable = _airtable()
        record = await airtable.find_by_call_sid(CallSid)
        if record:
            await airtable.update_interaction(
                record["id"],
                duration_seconds=int(CallDuration) if CallDuration else None,
                resolution_status=status_to_resolution[CallStatus],
            )

    return Response(content="", media_type="text/plain")


@router.post("/livekit/webhook")
async def livekit_webhook(request: Request) -> dict:
    """
    LiveKit room event webhook.
    Receives room_started, room_finished, participant_joined, participant_left events.
    """
    body = await request.json()
    event = body.get("event", "unknown")
    room = body.get("room", {})
    logger.info(
        "livekit.webhook_received",
        event=event,
        room_name=room.get("name"),
        num_participants=room.get("num_participants"),
    )
    return {"received": True}
