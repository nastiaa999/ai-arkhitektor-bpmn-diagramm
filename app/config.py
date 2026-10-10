"""Загрузка .env и models.yaml. Подстановка ${VAR} и ${VAR:-default}."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _VAR.sub(lambda m: os.environ.get(m.group(1)) or (m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def load_models() -> dict:
    raw = yaml.safe_load((ROOT / "app" / "models.yaml").read_text(encoding="utf-8"))
    return _expand(raw)


def resolve_profile(name: str | None = None) -> tuple[str, dict]:
    cfg = load_models()
    name = name or os.environ.get("LLM_PROFILE") or cfg["default"]
    if name not in cfg["models"]:
        raise KeyError(f"Профиль модели '{name}' не найден в models.yaml: {list(cfg['models'])}")
    return name, cfg["models"][name]


def runs_dir() -> Path:
    p = ROOT / "runs"
    p.mkdir(exist_ok=True)
    return p
