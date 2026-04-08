"""Unit tests for the __main__ entry point."""

from __future__ import annotations

from unittest.mock import patch


@patch("voice_assistant.__main__.uvicorn")
@patch("voice_assistant.__main__.settings")
def test_main_calls_uvicorn_run(mock_settings, mock_uvicorn):
    mock_settings.port = 9999

    from voice_assistant.__main__ import main

    main()

    mock_uvicorn.run.assert_called_once_with(
        "voice_assistant.app:app",
        host="0.0.0.0",
        port=9999,
        reload=False,
        log_level="info",
    )
