"""Tests for the /token endpoint rate limit."""

from unittest.mock import AsyncMock, patch


class TestTokenRateLimit:
    def test_trips_after_five_per_ip(self, client):
        with patch("app.routers.token.LiveKitAPI") as mock_api_cls:
            inst = mock_api_cls.return_value
            inst.room.create_room = AsyncMock()
            inst.aclose = AsyncMock()
            headers = {"X-Forwarded-For": "203.0.113.77"}  # unique IP → own bucket
            codes = [client.post("/token", headers=headers).status_code for _ in range(6)]

        assert codes[:5] == [200, 200, 200, 200, 200]
        assert codes[5] == 429
