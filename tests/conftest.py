"""Shared fixtures for cloudaura-voice test suite."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Set required env vars BEFORE any app module is imported,
# so pydantic-settings never touches a real .env file.
_TEST_ENV = {
    "LIVEKIT_URL": "wss://test.livekit.cloud",
    "LIVEKIT_API_KEY": "test-api-key",
    "LIVEKIT_API_SECRET": "test-api-secret",
    "LIVEKIT_SIP_HOST": "sip.test.livekit.cloud",
    "DEEPGRAM_API_KEY": "dg-test-key",
    "OPENAI_API_KEY": "sk-test-key",
    "TWILIO_ACCOUNT_SID": "AC_test_sid",
    "TWILIO_AUTH_TOKEN": "test_auth_token",
    "TWILIO_PHONE_NUMBER": "+15550001111",
    "AIRTABLE_API_KEY": "pat_test_key",
    "AIRTABLE_BASE_ID": "appTEST123",
    "AIRTABLE_TABLE_NAME": "TestInteractions",
    "ENVIRONMENT": "test",
    "PUBLIC_BASE_URL": "https://test.example.com",
    "LOG_LEVEL": "WARNING",
}

for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)


@pytest.fixture()
def client():
    """Return a synchronous TestClient wired to the FastAPI app."""
    # Clear the settings cache so each test gets fresh settings
    from app.config import get_settings
    get_settings.cache_clear()

    from app.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture()
def mock_twilio_client():
    """Patch the Twilio REST Client so TwilioService never makes real HTTP calls."""
    with patch("app.services.twilio_service.Client") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture()
def mock_airtable_api():
    """Patch the pyairtable Api so AirtableService never makes real HTTP calls."""
    with patch("app.services.airtable_service.Api") as mock_cls:
        mock_api = MagicMock()
        mock_table = MagicMock()
        mock_api.table.return_value = mock_table
        mock_cls.return_value = mock_api
        yield mock_table


@pytest.fixture()
def mock_request_validator():
    """Patch the Twilio RequestValidator."""
    with patch("app.services.twilio_service.RequestValidator") as mock_cls:
        mock_validator = MagicMock()
        mock_cls.return_value = mock_validator
        yield mock_validator


# ── Sample Payloads ──────────────────────────────────────────────────────────


@pytest.fixture()
def twilio_voice_payload():
    """Minimal form data that Twilio sends to the /webhooks/twilio/voice endpoint."""
    return {
        "CallSid": "CA1234567890abcdef1234567890abcdef",
        "From": "+15559998888",
        "To": "+15550001111",
        "CallStatus": "ringing",
    }


@pytest.fixture()
def twilio_status_payload_completed():
    """Form data for a completed-call status callback."""
    return {
        "CallSid": "CA1234567890abcdef1234567890abcdef",
        "CallStatus": "completed",
        "CallDuration": "42",
        "From": "+15559998888",
        "To": "+15550001111",
    }


@pytest.fixture()
def twilio_status_payload_failed():
    """Form data for a failed-call status callback."""
    return {
        "CallSid": "CAfailed0000000000000000000000000",
        "CallStatus": "failed",
        "CallDuration": None,
        "From": "+15559998888",
        "To": "+15550001111",
    }


@pytest.fixture()
def livekit_webhook_payload():
    """Sample LiveKit room event webhook body."""
    return {
        "event": "room_started",
        "room": {
            "name": "call_CA1234_-15559998888",
            "sid": "RM_test_room_sid",
            "num_participants": 1,
        },
    }
