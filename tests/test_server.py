"""Unit tests for FastAPI server endpoints."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from voice_assistant.app import app, _build_twiml


@pytest.fixture
def client():
    return TestClient(app)


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_build_twiml_contains_stream_url():
    twiml = _build_twiml("wss://example.com/ws/media-stream")
    assert 'url="wss://example.com/ws/media-stream"' in twiml
    assert "<Response>" in twiml
    assert "<Connect>" in twiml
    assert "<Stream" in twiml


def test_build_twiml_is_valid_xml():
    twiml = _build_twiml("wss://test.ngrok.io/ws/media-stream")
    assert twiml.startswith('<?xml version="1.0"')


@patch("voice_assistant.app.settings")
def test_voice_webhook_returns_twiml(mock_settings, client):
    mock_settings.public_url = "https://example.ngrok.io"
    mock_settings.validate.return_value = None
    mock_settings.default_language = "de-CH"
    mock_settings.language_profile.return_value = {"display": "Swiss German"}

    resp = client.post("/voice", data={"From": "+41791234567"})
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["content-type"]
    assert "wss://example.ngrok.io/ws/media-stream" in resp.text
