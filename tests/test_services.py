"""Unit tests for service classes (TwilioService, AirtableService)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.schemas import InteractionRecord, ResolutionStatus


class TestTwilioService:
    """Tests for app.services.twilio_service.TwilioService."""

    def _make_service(self, mock_client, mock_validator):
        """Instantiate TwilioService with external deps already patched."""
        with (
            patch("app.services.twilio_service.Client", return_value=mock_client),
            patch(
                "app.services.twilio_service.RequestValidator",
                return_value=mock_validator,
            ),
        ):
            from app.services.twilio_service import TwilioService
            return TwilioService()

    def test_build_sip_response_contains_sip_uri(
        self, mock_twilio_client, mock_request_validator
    ):
        svc = self._make_service(mock_twilio_client, mock_request_validator)
        twiml = svc.build_sip_response("call_CA123_-15559998888")

        assert "sip:" in twiml
        assert "call_CA123_-15559998888" in twiml
        assert "sip.livekit.cloud" in twiml
        assert "transport=tls" in twiml

    def test_build_sip_response_is_valid_xml(
        self, mock_twilio_client, mock_request_validator
    ):
        import xml.etree.ElementTree as ET

        svc = self._make_service(mock_twilio_client, mock_request_validator)
        twiml = svc.build_sip_response("room_test")

        root = ET.fromstring(twiml)
        assert root.tag == "Response"
        dial = root.find("Dial")
        assert dial is not None
        sip = dial.find("Sip")
        assert sip is not None

    def test_build_error_response_contains_message(
        self, mock_twilio_client, mock_request_validator
    ):
        svc = self._make_service(mock_twilio_client, mock_request_validator)
        twiml = svc.build_error_response("System unavailable")

        assert "System unavailable" in twiml
        assert "<Say" in twiml

    def test_build_error_response_is_valid_xml(
        self, mock_twilio_client, mock_request_validator
    ):
        import xml.etree.ElementTree as ET

        svc = self._make_service(mock_twilio_client, mock_request_validator)
        twiml = svc.build_error_response("Oops")

        root = ET.fromstring(twiml)
        assert root.tag == "Response"

    def test_validate_signature_delegates_to_twilio(
        self, mock_twilio_client, mock_request_validator
    ):
        mock_request_validator.validate.return_value = True
        svc = self._make_service(mock_twilio_client, mock_request_validator)

        result = svc.validate_signature(
            "https://example.com/webhook", {"Foo": "bar"}, "sig123"
        )
        assert result is True
        mock_request_validator.validate.assert_called_once_with(
            "https://example.com/webhook", {"Foo": "bar"}, "sig123"
        )

    def test_validate_signature_returns_false_on_invalid(
        self, mock_twilio_client, mock_request_validator
    ):
        mock_request_validator.validate.return_value = False
        svc = self._make_service(mock_twilio_client, mock_request_validator)

        result = svc.validate_signature("https://x.com", {}, "bad")
        assert result is False

    def test_get_call_returns_call_object(
        self, mock_twilio_client, mock_request_validator
    ):
        mock_call = MagicMock(sid="CA123", status="completed")
        mock_twilio_client.calls.return_value.fetch.return_value = mock_call

        svc = self._make_service(mock_twilio_client, mock_request_validator)
        call = svc.get_call("CA123")

        assert call.sid == "CA123"
        mock_twilio_client.calls.assert_called_once_with("CA123")

    def test_get_call_returns_none_on_error(
        self, mock_twilio_client, mock_request_validator
    ):
        mock_twilio_client.calls.return_value.fetch.side_effect = Exception("404")

        svc = self._make_service(mock_twilio_client, mock_request_validator)
        result = svc.get_call("CA_missing")

        assert result is None


class TestAirtableService:
    """Tests for app.services.airtable_service.AirtableService."""

    def _make_service(self, mock_table):
        """Instantiate AirtableService with the Api patched."""
        with patch("app.services.airtable_service.Api") as mock_api_cls:
            mock_api = MagicMock()
            mock_api.table.return_value = mock_table
            mock_api_cls.return_value = mock_api
            from app.services.airtable_service import AirtableService
            return AirtableService()

    @pytest.mark.asyncio
    async def test_create_interaction_sends_correct_fields(self, mock_airtable_api):
        mock_airtable_api.create.return_value = {"id": "recABC123"}

        svc = self._make_service(mock_airtable_api)
        record = InteractionRecord(
            call_sid="CA_test",
            caller_number="+15559998888",
            room_name="call_CA_test_-15559998888",
        )
        result = await svc.create_interaction(record)

        assert result == "recABC123"
        created_fields = mock_airtable_api.create.call_args[0][0]
        assert created_fields["caller_number"] == "+15559998888"
        assert "created_at" in created_fields

    @pytest.mark.asyncio
    async def test_create_interaction_returns_none_on_error(self, mock_airtable_api):
        mock_airtable_api.create.side_effect = Exception("API error")

        svc = self._make_service(mock_airtable_api)
        record = InteractionRecord(
            call_sid="CA_fail",
            caller_number="+15550000000",
            room_name="call_CA_fail_-15550000000",
        )
        result = await svc.create_interaction(record)

        assert result is None

    @pytest.mark.asyncio
    async def test_update_interaction_sends_duration(self, mock_airtable_api):
        svc = self._make_service(mock_airtable_api)
        result = await svc.update_interaction("recXYZ", duration_seconds=120)

        assert result is True
        mock_airtable_api.update.assert_called_once()
        updated_fields = mock_airtable_api.update.call_args[0][1]
        assert updated_fields["duration_seconds"] == 120

    @pytest.mark.asyncio
    async def test_update_interaction_sends_transcript(self, mock_airtable_api):
        svc = self._make_service(mock_airtable_api)
        result = await svc.update_interaction("recXYZ", transcript="Hello world")

        assert result is True
        updated_fields = mock_airtable_api.update.call_args[0][1]
        assert updated_fields["transcript"] == "Hello world"

    @pytest.mark.asyncio
    async def test_update_interaction_truncates_long_transcript(self, mock_airtable_api):
        svc = self._make_service(mock_airtable_api)
        long_text = "A" * 200_000
        await svc.update_interaction("recXYZ", transcript=long_text)

        updated_fields = mock_airtable_api.update.call_args[0][1]
        assert len(updated_fields["transcript"]) == 100_000

    @pytest.mark.asyncio
    async def test_update_interaction_skips_empty_fields(self, mock_airtable_api):
        svc = self._make_service(mock_airtable_api)
        result = await svc.update_interaction("recXYZ")

        assert result is True
        # No fields to update, so table.update should NOT be called
        mock_airtable_api.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_interaction_returns_false_on_error(self, mock_airtable_api):
        mock_airtable_api.update.side_effect = Exception("Network error")

        svc = self._make_service(mock_airtable_api)
        result = await svc.update_interaction("recXYZ", duration_seconds=10)

        assert result is False

    @pytest.mark.asyncio
    async def test_find_by_call_sid_returns_record(self, mock_airtable_api):
        mock_airtable_api.all.return_value = [
            {"id": "recFOUND", "fields": {"caller_number": "CA_target"}}
        ]

        svc = self._make_service(mock_airtable_api)
        result = await svc.find_by_call_sid("CA_target")

        assert result is not None
        assert result["id"] == "recFOUND"

    @pytest.mark.asyncio
    async def test_find_by_call_sid_returns_none_when_empty(self, mock_airtable_api):
        mock_airtable_api.all.return_value = []

        svc = self._make_service(mock_airtable_api)
        result = await svc.find_by_call_sid("CA_missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_call_sid_returns_none_on_error(self, mock_airtable_api):
        mock_airtable_api.all.side_effect = Exception("Timeout")

        svc = self._make_service(mock_airtable_api)
        result = await svc.find_by_call_sid("CA_err")

        assert result is None


class TestTelnyxService:
    """Tests for app.services.telnyx_service.TelnyxService (pure parsers)."""

    def _make_service(self):
        with patch("app.services.telnyx_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                telnyx_assistant_id="assistant-test",
                telnyx_api_key="KEY_test",
            )
            from app.services.telnyx_service import TelnyxService
            return TelnyxService()

    def test_parse_call_control_webhook_extracts_inbound_call(self):
        svc = self._make_service()
        body = {
            "data": {
                "event_type": "call.initiated",
                "payload": {
                    "call_control_id": "cc_abc123",
                    "call_leg_id": "leg_xyz",
                    "from": "+15551112222",
                    "to": "+14254339697",
                    "direction": "inbound",
                    "state": "parked",
                },
            }
        }
        result = svc.parse_call_control_webhook(body)
        assert result["event_type"] == "call.initiated"
        assert result["call_control_id"] == "cc_abc123"
        assert result["caller_number"] == "+15551112222"
        assert result["direction"] == "inbound"

    def test_parse_call_control_webhook_handles_missing_payload(self):
        svc = self._make_service()
        result = svc.parse_call_control_webhook({})
        assert result["event_type"] == "unknown"
        assert result["call_control_id"] == ""
        assert result["direction"] == "inbound"

    def test_is_terminal_event_recognises_hangup(self):
        svc = self._make_service()
        assert svc.is_terminal_event("call.hangup") is True
        assert svc.is_terminal_event("call.machine.detection.ended") is True
        assert svc.is_terminal_event("call.answered") is False
        assert svc.is_terminal_event("call.initiated") is False

    def test_map_to_resolution_normal_clearing_is_resolved(self):
        svc = self._make_service()
        assert svc.map_to_resolution("call.hangup", "normal_clearing") == "resolved"
        assert svc.map_to_resolution("completed", "") == "resolved"

    def test_map_to_resolution_failure_causes_dropped(self):
        svc = self._make_service()
        assert svc.map_to_resolution("call.hangup", "user_busy") == "dropped"
        assert svc.map_to_resolution("failed", "") == "dropped"

    def test_parse_voice_webhook_texml_flat_payload(self):
        svc = self._make_service()
        body = {
            "CallSid": "v3:abc",
            "From": "+15558675309",
            "To": "+14254339697",
            "CallStatus": "ringing",
            "Direction": "inbound",
        }
        result = svc.parse_voice_webhook(body)
        assert result["call_control_id"] == "v3:abc"
        assert result["caller_number"] == "+15558675309"
        assert result["direction"] == "inbound"
