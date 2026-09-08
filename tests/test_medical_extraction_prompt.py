"""Tests for backend/documents/extraction.py's JSON-array parsing -- pure
logic, no LLM calls (mirrors how memory/extraction.py's parser is tested)."""
from backend.documents.extraction import _extract_json_array


def test_parses_valid_array():
    text = '[{"fact": "Diagnosed with type 2 diabetes in 2019", "confidence": 0.9}]'
    result = _extract_json_array(text)
    assert result == [{"fact": "Diagnosed with type 2 diabetes in 2019", "confidence": 0.9}]


def test_parses_empty_array():
    assert _extract_json_array("[]") == []


def test_parses_array_wrapped_in_prose():
    text = 'Here are the facts:\n[{"fact": "HbA1c 7.2 on 2026-01-15", "confidence": 0.8}]\nDone.'
    result = _extract_json_array(text)
    assert result == [{"fact": "HbA1c 7.2 on 2026-01-15", "confidence": 0.8}]


def test_returns_none_for_malformed_json():
    text = '[{"fact": "missing closing brace", "confidence": 0.8]'
    assert _extract_json_array(text) is None


def test_returns_none_for_no_array_at_all():
    assert _extract_json_array("Nothing extractable here.") is None


def test_returns_none_for_json_object_not_array():
    assert _extract_json_array('{"fact": "not an array"}') is None
