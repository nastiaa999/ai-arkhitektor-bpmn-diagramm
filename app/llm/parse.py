"""Устойчивый разбор ответа LLM в JSON."""
from __future__ import annotations

import json
import re

try:
    import json_repair
except ImportError:  # pragma: no cover
    json_repair = None

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


class JSONParseError(ValueError):
    pass


def clean_response(text: str) -> str:
    text = _THINK.sub("", text or "")
    text = re.sub(r"^.*?</think>", "", text, flags=re.DOTALL)  # незакрытый/оборванный <think>
    m = _FENCE.search(text)
    if m:
        text = m.group(1)
    return text.strip()


def extract_json(text: str) -> dict:
    """Снять think/ограждения, взять внешний {...}, json.loads, при ошибке json_repair."""
    text = clean_response(text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1:
        raise JSONParseError("В ответе нет JSON-объекта")
    chunk = text[start:end + 1] if end > start else text[start:]
    try:
        data = json.loads(chunk)
    except json.JSONDecodeError as e:
        if json_repair is None:
            raise JSONParseError(f"Невалидный JSON: {e}") from e
        try:
            data = json_repair.loads(text[start:])
        except Exception as e2:  # noqa: BLE001
            raise JSONParseError(f"Невалидный JSON: {e2}") from e2
    if not isinstance(data, dict):
        raise JSONParseError("Ожидался JSON-объект верхнего уровня")
    return data
