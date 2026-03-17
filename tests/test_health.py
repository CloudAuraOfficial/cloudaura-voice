"""Tests for the /health endpoint."""

import pytest


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_body(self, client):
        data = client.get("/health").json()
        assert data["status"] == "ok"
        assert "environment" in data
        assert "version" in data

    def test_health_response_schema(self, client):
        data = client.get("/health").json()
        expected_keys = {"status", "environment", "version"}
        assert expected_keys.issubset(set(data.keys()))

    def test_health_version_format(self, client):
        data = client.get("/health").json()
        parts = data["version"].split(".")
        assert len(parts) == 3, "Version should follow semver (x.y.z)"
