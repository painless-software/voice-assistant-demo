"""Unit tests for goodbye detection in call_handler."""

from __future__ import annotations

import pytest

from voice_assistant.call_handler import _is_goodbye, GOODBYE_PATTERNS


@pytest.mark.parametrize(
    "text",
    [
        "Goodbye",
        "bye",
        "tschüss",
        "tschüssi",
        "auf wiederhören",
        "ciao",
        "arrivederci",
        "merci beaucoup",
        "danke schön",
        "that's all",
        "that is it",
        "see you later",
        "have a nice day",
        "no need to continue",
    ],
)
def test_is_goodbye_positive(text):
    assert _is_goodbye(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "What is the weather?",
        "Tell me more",
        "I have a question",
        "Can you help me?",
        "",
    ],
)
def test_is_goodbye_negative(text):
    assert _is_goodbye(text) is False


def test_is_goodbye_strips_punctuation():
    assert _is_goodbye("Goodbye!") is True
    assert _is_goodbye("bye.") is True


def test_is_goodbye_case_insensitive():
    assert _is_goodbye("GOODBYE") is True
    assert _is_goodbye("Tschüss") is True


def test_goodbye_patterns_is_nonempty():
    assert len(GOODBYE_PATTERNS) > 0
