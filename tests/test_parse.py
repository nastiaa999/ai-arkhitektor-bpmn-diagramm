from app.llm.parse import JSONParseError, extract_json
import pytest


def test_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_think_and_fence():
    t = '<think>рассуждаю {нет}</think>\n```json\n{"a": [1, 2]}\n```\nготово'
    assert extract_json(t) == {"a": [1, 2]}


def test_text_around():
    assert extract_json('Вот ответ: {"x": "y"} спасибо') == {"x": "y"}


def test_broken_json_repaired():
    d = extract_json('{"steps": [{"id": "S1", "name": "a",}, {"id": "S2"}')
    assert d["steps"][0]["id"] == "S1"


def test_no_json():
    with pytest.raises(JSONParseError):
        extract_json("извините, не могу")
