import httpx
import structlog
from typing import Any, Optional

from app.config import get_settings

logger = structlog.get_logger(__name__)


class TelnyxService:
    """Handles Telnyx webhook processing and AI Assistant integration."""

    BASE_URL = "https://api.telnyx.com/v2"

    def __init__(self) -> None:
        settings = get_settings()
        self._assistant_id = settings.telnyx_assistant_id
        self._api_key = settings.telnyx_api_key

    async def answer_call(self, call_control_id: str) -> dict[str, Any]:
        """Answer an inbound call via Call Control API."""
        url = f"{self.BASE_URL}/calls/{call_control_id}/actions/answer"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"client_state": "answered"},
            )
            resp.raise_for_status()
            return resp.json()

    async def start_ai_assistant(self, call_control_id: str) -> dict[str, Any]:
        """Start the AI Assistant on a call via Call Control API."""
        url = f"{self.BASE_URL}/calls/{call_control_id}/actions/ai_assistant_start"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"id": self._assistant_id},
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def parse_voice_webhook(body: dict[str, Any]) -> dict[str, Any]:
        """Extract call metadata from a Telnyx TeXML voice webhook.

        TeXML webhooks arrive as form-encoded or JSON with flat fields
        like CallSid, From, To, etc.
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
    def parse_call_control_webhook(body: dict[str, Any]) -> dict[str, Any]:
        """Extract call metadata from a Telnyx Call Control webhook."""
        data = body.get("data", {})
        payload = data.get("payload", {})
        return {
            "event_type": data.get("event_type", "unknown"),
            "call_control_id": payload.get("call_control_id", ""),
            "call_leg_id": payload.get("call_leg_id", ""),
            "caller_number": payload.get("from", ""),
            "called_number": payload.get("to", ""),
            "direction": payload.get("direction", "inbound"),
            "state": payload.get("state", ""),
            "client_state": payload.get("client_state", ""),
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
    def is_terminal_event(event_type: str) -> bool:
        """Check if a Call Control event represents a terminal state."""
        return event_type in {"call.hangup", "call.machine.detection.ended"}

    @staticmethod
    def map_to_resolution(event_type: str, hangup_cause: str = "") -> str:
        """Map event type to resolution status."""
        if event_type in ("completed", "call.hangup") and hangup_cause in (
            "", "normal_clearing", "originator_cancel"
        ):
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
