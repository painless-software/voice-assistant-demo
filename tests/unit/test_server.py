"""Unit tests for FastAPI server endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from voice_assistant.app import app, _build_twiml, _lifespan, media_stream_ws


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


@patch("voice_assistant.app.settings")
def test_voice_webhook_http_url(mock_settings, client):
    mock_settings.public_url = "http://localhost:8080"
    mock_settings.validate.return_value = None
    mock_settings.default_language = "de-CH"
    mock_settings.language_profile.return_value = {"display": "Swiss German"}

    resp = client.post("/voice", data={"From": "+41791234567"})
    assert "ws://localhost:8080/ws/media-stream" in resp.text


@patch("voice_assistant.app.settings")
def test_voice_webhook_bare_url(mock_settings, client):
    mock_settings.public_url = "example.com"
    mock_settings.validate.return_value = None
    mock_settings.default_language = "de-CH"
    mock_settings.language_profile.return_value = {"display": "Swiss German"}

    resp = client.post("/voice", data={"From": "+41791234567"})
    assert "wss://example.com/ws/media-stream" in resp.text


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@patch("voice_assistant.app.settings")
async def test_lifespan_validates_settings(mock_settings):
    async with _lifespan(app):
        pass
    mock_settings.validate.assert_called_once()


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@patch("voice_assistant.app.handle_media_stream", new_callable=AsyncMock)
async def test_media_stream_ws_delegates_to_handler(mock_handler):
    ws = AsyncMock()
    await media_stream_ws(ws)
    mock_handler.assert_awaited_once_with(ws)
