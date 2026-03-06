import structlog
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.voice_response import Dial, VoiceResponse

from app.config import get_settings

logger = structlog.get_logger(__name__)


class TwilioService:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        self._validator = RequestValidator(settings.twilio_auth_token)
        self._settings = settings

    def validate_signature(self, url: str, params: dict, signature: str) -> bool:
        """Verify the request genuinely originated from Twilio."""
        return self._validator.validate(url, params, signature)

    def build_sip_response(self, room_name: str) -> str:
        """
        Return TwiML that routes the inbound call into a LiveKit room via SIP.
        LiveKit SIP trunk must be pre-configured to accept calls from Twilio.
        """
        settings = self._settings
        sip_uri = f"sip:{room_name}@{settings.livekit_sip_host};transport=tls"

        response = VoiceResponse()
        dial = Dial(answer_on_bridge=True)
        dial.sip(sip_uri)
        response.append(dial)

        twiml = str(response)
        logger.info(
            "twilio.sip_response_built",
            room_name=room_name,
            sip_uri=sip_uri,
        )
        return twiml

    def build_error_response(self, message: str) -> str:
        """Return TwiML that reads an error message and hangs up."""
        response = VoiceResponse()
        response.say(message, voice="Polly.Joanna")
        return str(response)

    def get_call(self, call_sid: str):
        """Fetch live call details from the Twilio API."""
        try:
            return self._client.calls(call_sid).fetch()
        except Exception as exc:
            logger.error("twilio.fetch_call_failed", call_sid=call_sid, error=str(exc))
            return None
