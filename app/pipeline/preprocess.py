"""M1. Нормализация текста и нумерация предложений."""
from __future__ import annotations

import re

from app.model.ir import Sentence

try:
    from razdel import sentenize
except ImportError:  # pragma: no cover
    sentenize = None

MAX_CHARS = 20_000
MAX_SENTENCES = 150
_LIST_ITEM = re.compile(r"^\s*(?:[-–—•*]|\d+[.)]|\d+\.\d+[.)]?)\s+")


class EmptyText(ValueError):
    pass


def _split(paragraph: str) -> list[str]:
    if sentenize:
        return [s.text.strip() for s in sentenize(paragraph) if s.text.strip()]
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z0-9])", paragraph) if s.strip()]


def split_sentences(text: str) -> tuple[list[Sentence], list[str]]:
    """Вернуть (предложения, предупреждения)."""
    warnings: list[str] = []
    text = (text or "").replace("\r\n", "\n").replace("\u00a0", " ")
    if not text.strip():
        raise EmptyText("Пустой текст процесса")
    if len(text) > MAX_CHARS:
        warnings.append(f"Текст длиннее {MAX_CHARS} символов — обрезан")
        text = text[:MAX_CHARS]

    parts: list[str] = []
    buf: list[str] = []  # накопленные строки текущего абзаца (мягкие переносы склеиваются)

    def flush() -> None:
        if buf:
            paragraph = re.sub(r"\s+", " ", " ".join(buf)).strip()
            if paragraph:
                parts.extend(re.sub(r"\s+", " ", s) for s in _split(paragraph))
            buf.clear()

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            flush()                               # пустая строка — конец абзаца
            continue
        if _LIST_ITEM.match(line):                # пункт списка — отдельное предложение
            flush()                               # не склеивать с предыдущим абзацем
            parts.append(re.sub(r"\s+", " ", _LIST_ITEM.sub("", line)).strip())
        else:
            buf.append(line)                      # обычная строка — копим в абзац
    flush()

    sentences = [Sentence(n=i, text=t) for i, t in enumerate(parts, 1) if t]
    if len(sentences) > MAX_SENTENCES:
        warnings.append(f"{len(sentences)} предложений (> {MAX_SENTENCES}): качество может снизиться")
    return sentences, warnings


def numbered(sentences: list[Sentence]) -> str:
    return "\n".join(f"[{s.n}] {s.text}" for s in sentences)
