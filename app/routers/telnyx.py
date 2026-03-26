import structlog
from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.models.schemas import InteractionRecord, ResolutionStatus
from app.services.airtable_service import AirtableService
from app.services.telnyx_service import TelnyxService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/telnyx", tags=["telnyx"])


def _telnyx() -> TelnyxService:
    return TelnyxService()


def _airtable() -> AirtableService:
    return AirtableService()


@router.post("/voice", response_class=Response)
async def telnyx_voice_webhook(request: Request):
    """TeXML endpoint that routes inbound calls to the Nova AI Assistant.

    Parses the Telnyx webhook payload, logs the call to Airtable,
    and returns TeXML connecting to the AI Assistant.
    """
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
    log.info("telnyx.inbound_call")

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

    try:
        texml = telnyx.build_ai_assistant_response()
    except Exception as exc:
        log.error("telnyx.voice_webhook_error", error=str(exc))
        texml = telnyx.build_error_response(
            "We're sorry, the assistant is temporarily unavailable. Please try again shortly."
        )

    return Response(content=texml, media_type="application/xml")


@router.post("/status", response_class=Response)
async def telnyx_status_webhook(request: Request):
    """Receives call status updates from Telnyx.

    On terminal states (hangup, completed, failed), updates the
    Airtable record with duration and resolution.
    """
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
