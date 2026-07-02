"""Tests for Twilio + Telnyx webhook signature verification."""

import base64
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from twilio.request_validator import RequestValidator


# ── Twilio X-Twilio-Signature ─────────────────────────────────────────────────


class TestTwilioSignature:
    def test_forged_request_rejected(self, client, twilio_voice_payload):
        # No X-Twilio-Signature header → real validator rejects with 403.
        resp = client.post("/webhooks/twilio/voice", data=twilio_voice_payload)
        assert resp.status_code == 403
        assert resp.json() == {"error": "Invalid Twilio signature"}

    def test_valid_signature_accepted(self, client, twilio_voice_payload):
        url = "https://test.example.com/webhooks/twilio/voice"  # PUBLIC_BASE_URL + path
        sig = RequestValidator("test_auth_token").compute_signature(
            url, twilio_voice_payload
        )
        resp = client.post(
            "/webhooks/twilio/voice",
            data=twilio_voice_payload,
            headers={"X-Twilio-Signature": sig},
        )
        assert resp.status_code == 200


# ── Telnyx Ed25519 ────────────────────────────────────────────────────────────


def _sign(priv: Ed25519PrivateKey, timestamp: str, body: bytes) -> str:
    return base64.b64encode(priv.sign(f"{timestamp}|".encode() + body)).decode()


class TestTelnyxSignature:
    def test_unsigned_request_fails_closed(self, client):
        # Test env sets no TELNYX_PUBLIC_KEY → must reject rather than accept.
        resp = client.post(
            "/telnyx/webhook", json={"data": {"event_type": "call.initiated"}}
        )
        assert resp.status_code == 403
        assert resp.json() == {"error": "Invalid Telnyx signature"}

    def test_verify_signature_paths(self):
        from app.services.telnyx_service import TelnyxService

        priv = Ed25519PrivateKey.generate()
        pub_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode()
        ts = str(int(time.time()))
        body = b'{"data":{"event_type":"call.initiated"}}'
        sig = _sign(priv, ts, body)

        svc = TelnyxService()
        svc._public_key = pub_b64

        assert svc.verify_signature(body, sig, ts) is True          # happy path
        assert svc.verify_signature(body + b"x", sig, ts) is False   # tampered body
        old_ts = str(int(time.time()) - 3600)                        # correct sig, stale ts
        assert svc.verify_signature(body, _sign(priv, old_ts, body), old_ts) is False

        svc._public_key = ""                                         # fail closed
        assert svc.verify_signature(body, sig, ts) is False
