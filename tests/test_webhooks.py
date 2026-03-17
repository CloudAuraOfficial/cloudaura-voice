"""Tests for the webhook endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTwilioVoiceWebhook:
    """Tests for POST /webhooks/twilio/voice."""

    def test_returns_twiml_xml(self, client, twilio_voice_payload):
        with patch("app.routers.webhooks._twilio") as mock_factory:
            svc = MagicMock()
            svc.build_sip_response.return_value = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<Response><Dial><Sip>sip:room@host</Sip></Dial></Response>"
            )
            mock_factory.return_value = svc

            response = client.post(
                "/webhooks/twilio/voice", data=twilio_voice_payload
            )
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/xml"
            assert "<Response>" in response.text

    def test_room_name_derived_from_callsid(self, client, twilio_voice_payload):
        with patch("app.routers.webhooks._twilio") as mock_factory:
            svc = MagicMock()
            svc.build_sip_response.return_value = "<Response/>"
            mock_factory.return_value = svc

            client.post("/webhooks/twilio/voice", data=twilio_voice_payload)

            room_arg = svc.build_sip_response.call_args[0][0]
            assert twilio_voice_payload["CallSid"] in room_arg
            # '+' should be replaced with '-'
            assert "+" not in room_arg

    def test_error_fallback_when_sip_fails(self, client, twilio_voice_payload):
        with patch("app.routers.webhooks._twilio") as mock_factory:
            svc = MagicMock()
            svc.build_sip_response.side_effect = RuntimeError("SIP down")
            svc.build_error_response.return_value = (
                "<Response><Say>Sorry</Say></Response>"
            )
            mock_factory.return_value = svc

            response = client.post(
                "/webhooks/twilio/voice", data=twilio_voice_payload
            )
            assert response.status_code == 200
            svc.build_error_response.assert_called_once()

    def test_missing_callsid_returns_422(self, client):
        incomplete = {
            "From": "+15559998888",
            "To": "+15550001111",
            "CallStatus": "ringing",
        }
        response = client.post("/webhooks/twilio/voice", data=incomplete)
        assert response.status_code == 422

    def test_missing_from_returns_422(self, client):
        incomplete = {
            "CallSid": "CAmissing",
            "To": "+15550001111",
            "CallStatus": "ringing",
        }
        response = client.post("/webhooks/twilio/voice", data=incomplete)
        assert response.status_code == 422

    def test_missing_all_fields_returns_422(self, client):
        response = client.post("/webhooks/twilio/voice", data={})
        assert response.status_code == 422


class TestTwilioStatusWebhook:
    """Tests for POST /webhooks/twilio/status."""

    def test_completed_call_updates_airtable(
        self, client, twilio_status_payload_completed
    ):
        with patch("app.routers.webhooks._airtable") as mock_factory:
            svc = AsyncMock()
            svc.find_by_call_sid.return_value = {
                "id": "rec123",
                "fields": {"caller_number": "+15559998888"},
            }
            svc.update_interaction.return_value = True
            mock_factory.return_value = svc

            response = client.post(
                "/webhooks/twilio/status", data=twilio_status_payload_completed
            )
            assert response.status_code == 200

            svc.find_by_call_sid.assert_awaited_once_with(
                twilio_status_payload_completed["CallSid"]
            )
            svc.update_interaction.assert_awaited_once()
            call_kwargs = svc.update_interaction.call_args.kwargs
            assert call_kwargs["duration_seconds"] == 42

    def test_failed_call_marks_dropped(self, client, twilio_status_payload_failed):
        with patch("app.routers.webhooks._airtable") as mock_factory:
            svc = AsyncMock()
            svc.find_by_call_sid.return_value = {
                "id": "rec456",
                "fields": {},
            }
            svc.update_interaction.return_value = True
            mock_factory.return_value = svc

            response = client.post(
                "/webhooks/twilio/status", data=twilio_status_payload_failed
            )
            assert response.status_code == 200
            svc.update_interaction.assert_awaited_once()

    def test_non_terminal_status_does_not_update(self, client):
        payload = {
            "CallSid": "CAringing",
            "CallStatus": "ringing",
            "From": "+15559998888",
            "To": "+15550001111",
        }
        with patch("app.routers.webhooks._airtable") as mock_factory:
            svc = AsyncMock()
            mock_factory.return_value = svc

            response = client.post("/webhooks/twilio/status", data=payload)
            assert response.status_code == 200
            svc.find_by_call_sid.assert_not_awaited()

    def test_terminal_status_no_record_found(self, client):
        payload = {
            "CallSid": "CAnorecord",
            "CallStatus": "completed",
            "CallDuration": "10",
            "From": "+15559998888",
            "To": "+15550001111",
        }
        with patch("app.routers.webhooks._airtable") as mock_factory:
            svc = AsyncMock()
            svc.find_by_call_sid.return_value = None
            mock_factory.return_value = svc

            response = client.post("/webhooks/twilio/status", data=payload)
            assert response.status_code == 200
            svc.update_interaction.assert_not_awaited()

    def test_missing_callsid_returns_422(self, client):
        incomplete = {
            "CallStatus": "completed",
            "From": "+15559998888",
            "To": "+15550001111",
        }
        response = client.post("/webhooks/twilio/status", data=incomplete)
        assert response.status_code == 422


class TestLiveKitWebhook:
    """Tests for POST /webhooks/livekit/webhook.

    NOTE: The current livekit_webhook handler has a structlog bug — the local
    variable ``event`` shadows structlog's positional ``event`` parameter,
    causing a TypeError. These tests document the known bug and will be
    updated once the handler is fixed (rename the local var to ``event_type``).
    """

    def test_raises_due_to_structlog_event_collision(
        self, client, livekit_webhook_payload
    ):
        """Tracks known bug: structlog.info('event_name', event=var) fails."""
        with pytest.raises(TypeError, match="multiple values for argument 'event'"):
            client.post(
                "/webhooks/livekit/webhook", json=livekit_webhook_payload
            )

    def test_payload_without_event_key_also_collides(self, client):
        """When 'event' defaults to 'unknown', the same collision still occurs."""
        with pytest.raises(TypeError, match="multiple values for argument 'event'"):
            client.post(
                "/webhooks/livekit/webhook", json={"room": {"name": "test"}}
            )
