import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.models.schemas import InteractionRecord, ResolutionStatus
from app.services.airtable_service import AirtableService
from app.services.telnyx_service import TelnyxService, _safe_int

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/telnyx", tags=["telnyx"])


def _telnyx() -> TelnyxService:
    return TelnyxService()


def _airtable() -> AirtableService:
    return AirtableService()


@router.post("/voice", response_class=Response)
async def telnyx_voice_webhook(request: Request):
    """TeXML voice webhook — answers inbound calls with a Say verb for testing,
    then transfers to the AI Assistant via Call Control API."""
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            body = await request.json()
        else:
            form = await request.form()
            body = dict(form)
    except Exception:
        body = {}

    telnyx = _telnyx()
    call_data = telnyx.parse_voice_webhook(body)

    log = logger.bind(
        call_control_id=call_data["call_control_id"],
        caller=call_data["caller_number"],
        direction=call_data["direction"],
    )
    log.info("telnyx.voice_webhook_received")

    # Log call to Airtable
    if call_data["caller_number"]:
        try:
            airtable = _airtable()
            record = InteractionRecord(
                call_sid=call_data["call_control_id"] or "telnyx-unknown",
                caller_number=call_data["caller_number"],
                room_name=f"telnyx_{call_data['call_control_id']}",
            )
            await airtable.create_interaction(record)
        except Exception as exc:
            log.warning("telnyx.airtable_create_failed", error=str(exc))

    # If we have a call_control_id, start the AI assistant via Call Control API
    if call_data["call_control_id"]:
        try:
            await telnyx.start_ai_assistant(call_data["call_control_id"])
            log.info("telnyx.ai_assistant_started_via_texml")
            # Return empty response — Call Control API takes over
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                media_type="application/xml",
            )
        except Exception as exc:
            log.error("telnyx.ai_assistant_start_failed", error=str(exc))

    # Fallback: Say a message
    texml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Hello! This is the Aura voice system. The AI assistant is currently being configured. Please try again shortly.</Say>
    <Hangup/>
</Response>"""

    return Response(content=texml, media_type="application/xml")


@router.post("/status", response_class=Response)
async def telnyx_status_webhook(request: Request):
    """Receives call status updates from Telnyx TeXML."""
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            body = await request.json()
        else:
            form = await request.form()
            body = dict(form)
    except Exception:
        body = {}

    telnyx = _telnyx()
    status_data = telnyx.parse_status_webhook(body)

    log = logger.bind(
        call_control_id=status_data["call_control_id"],
        call_status=status_data["call_status"],
    )
    log.info("telnyx.status_callback")

    if telnyx.is_terminal_status(status_data["call_status"]):
        resolution = telnyx.map_to_resolution(status_data["call_status"])
        resolution_status = (
            ResolutionStatus.RESOLVED if resolution == "resolved" else ResolutionStatus.DROPPED
        )

        airtable = _airtable()
        record = await airtable.find_by_call_sid(status_data["call_control_id"])
        if record:
            await airtable.update_interaction(
                record["id"],
                duration_seconds=status_data["duration_seconds"],
                resolution_status=resolution_status,
            )
            log.info("telnyx.airtable_updated", airtable_id=record["id"])
        else:
            log.warning("telnyx.airtable_record_not_found")

    return Response(content="<Response/>", media_type="application/xml")


@router.post("/webhook")
async def telnyx_call_control_webhook(request: Request):
    """Call Control webhook for the Call Control application.

    Handles the full call lifecycle:
    1. call.initiated → answer the call
    2. call.answered → start AI assistant
    3. call.hangup → log final state
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "invalid_payload"}, status_code=400)

    telnyx = _telnyx()
    event = telnyx.parse_call_control_webhook(body)
    event_type = event["event_type"]

    log = logger.bind(
        event_type=event_type,
        call_control_id=event["call_control_id"],
        caller=event["caller_number"],
        direction=event["direction"],
    )
    log.info("telnyx.call_control_webhook_received")

    if event_type == "call.initiated" and event["direction"] == "inbound":
        try:
            await telnyx.answer_call(event["call_control_id"])
            log.info("telnyx.call_answered")
        except Exception as exc:
            log.error("telnyx.answer_failed", error=str(exc))
            return JSONResponse({"status": "answer_failed"}, status_code=500)

        if event["caller_number"]:
            try:
                airtable = _airtable()
                record = InteractionRecord(
                    call_sid=event["call_control_id"] or "telnyx-unknown",
                    caller_number=event["caller_number"],
                    room_name=f"telnyx_{event['call_leg_id']}",
                )
                await airtable.create_interaction(record)
            except Exception as exc:
                log.warning("telnyx.airtable_create_failed", error=str(exc))

    elif event_type == "call.answered":
        try:
            result = await telnyx.start_ai_assistant(event["call_control_id"])
            log.info("telnyx.ai_assistant_started", result=result)
        except Exception as exc:
            log.error("telnyx.ai_assistant_start_failed", error=str(exc))

    elif telnyx.is_terminal_event(event_type):
        payload = body.get("data", {}).get("payload", {})
        hangup_cause = payload.get("hangup_cause", "")
        duration_secs = payload.get("duration_secs")

        resolution = telnyx.map_to_resolution(event_type, hangup_cause)
        resolution_status = (
            ResolutionStatus.RESOLVED if resolution == "resolved" else ResolutionStatus.DROPPED
        )

        try:
            airtable = _airtable()
            record = await airtable.find_by_call_sid(event["call_control_id"])
            if record:
                await airtable.update_interaction(
                    record["id"],
                    duration_seconds=_safe_int(duration_secs),
                    resolution_status=resolution_status,
                )
                log.info("telnyx.airtable_updated", airtable_id=record["id"])
            else:
                log.warning("telnyx.airtable_record_not_found")
        except Exception as exc:
            log.warning("telnyx.airtable_update_failed", error=str(exc))

    return JSONResponse({"status": "ok"})
