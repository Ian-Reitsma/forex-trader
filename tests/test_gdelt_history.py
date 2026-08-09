from __future__ import annotations

import json

import pytest

from forex_trader.research.gdelt_history import parse_dirty_gdelt_json


def test_dirty_gdelt_json_repairs_only_invalid_backslash_escape() -> None:
    raw = r'{"articles":[{"title":"Fed rate path C:\markets\quotes","url":"https://example.com"}]}'
    parsed = parse_dirty_gdelt_json(raw)
    assert isinstance(parsed, dict)
    articles = parsed["articles"]
    assert articles[0]["title"] == r"Fed rate path C:\markets\quotes"


def test_dirty_gdelt_json_keeps_valid_json_unchanged() -> None:
    raw = json.dumps({"articles": [{"title": "Fed rate cut\nnext meeting"}]})
    assert parse_dirty_gdelt_json(raw) == json.loads(raw)


def test_dirty_gdelt_json_rejects_nonrepairable_payload() -> None:
    with pytest.raises(ValueError, match="invalid"):
        parse_dirty_gdelt_json('{"articles": [}')
