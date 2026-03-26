import hashlib
import hmac
import time
from typing import Any, Optional

import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)


class TelnyxService:
    """Handles Telnyx TeXML webhook processing and response generation."""

    def __init__(self) -> None:
        settings = get_settings()
        self._assistant_id = settings.telnyx_assistant_id
        self._api_key = settings.telnyx_api_key

    def build_ai_assistant_response(self) -> str:
        """Return TeXML that connects the call to the Telnyx AI Assistant."""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <AIAssistant id="{self._assistant_id}">
        </AIAssistant>
    </Connect>
</Response>"""

    def build_error_response(self, message: str) -> str:
        """Return TeXML that speaks an error message and hangs up."""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>{message}</Say>
    <Hangup/>
</Response>"""

    @staticmethod
    def parse_voice_webhook(body: dict[str, Any]) -> dict[str, Any]:
        """Extract call metadata from a Telnyx voice webhook payload.

        Telnyx sends webhooks as JSON with call details nested under
        'data.payload' for event-based webhooks, or as form-encoded
        TeXML-style params (CallSid, From, To, etc.).
        """
        # TeXML-style flat payload (form-encoded forwarded as dict)
        if "CallSid" in body or "From" in body:
            return {
                "call_control_id": body.get("CallSid", body.get("CallControlId", "")),
                "caller_number": body.get("From", ""),
                "called_number": body.get("To", ""),
                "call_status": body.get("CallStatus", "initiated"),
                "direction": body.get("Direction", "inbound"),
            }

        # Event API-style nested payload
        data = body.get("data", {})
        payload = data.get("payload", data)
        return {
            "call_control_id": payload.get("call_control_id", ""),
            "caller_number": payload.get("from", payload.get("caller_id_number", "")),
            "called_number": payload.get("to", ""),
            "call_status": data.get("event_type", "unknown"),
            "direction": payload.get("direction", "inbound"),
        }

    @staticmethod
    def parse_status_webhook(body: dict[str, Any]) -> dict[str, Any]:
        """Extract status info from a Telnyx status callback."""
        # TeXML-style
        if "CallStatus" in body:
            return {
                "call_control_id": body.get("CallSid", body.get("CallControlId", "")),
                "call_status": body.get("CallStatus", "unknown"),
                "duration_seconds": _safe_int(body.get("CallDuration")),
                "caller_number": body.get("From", ""),
            }

        # Event API-style
        data = body.get("data", {})
        payload = data.get("payload", data)
        event_type = data.get("event_type", payload.get("event_type", "unknown"))
        return {
            "call_control_id": payload.get("call_control_id", ""),
            "call_status": event_type,
            "duration_seconds": _safe_int(payload.get("duration_secs")),
            "caller_number": payload.get("from", payload.get("caller_id_number", "")),
        }

    @staticmethod
    def is_terminal_status(status: str) -> bool:
        """Check if a Telnyx call status represents a terminal state."""
        terminal = {
            "completed",
            "failed",
            "busy",
            "no-answer",
            "canceled",
            "call.hangup",
            "call.machine.detection.ended",
        }
        return status in terminal

    @staticmethod
    def map_to_resolution(status: str) -> str:
        """Map Telnyx call status to ResolutionStatus value."""
        if status in ("completed", "call.hangup"):
            return "resolved"
        return "dropped"


def _safe_int(value: Any) -> Optional[int]:
    """Convert a value to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None
