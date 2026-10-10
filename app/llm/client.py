"""M0. Единственная точка обращения к LLM.

Провайдеры:
  * GigaChatClient   — OAuth + REST GigaChat (бесплатный тариф PERS), без SDK
  * OpenAICompatClient — всё OpenAI-совместимое (vLLM, OpenRouter, Yandex AI Studio)
Выбор — по профилю из models.yaml (LLM_PROFILE в .env или параметр model).
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

import httpx

from app.config import resolve_profile
from app.llm.parse import JSONParseError, extract_json


class LLMError(Exception):
    pass


class LLMUnavailable(LLMError):
    """Модель недоступна (сеть, ключ, 5xx после повторов). API отдаёт 502."""


class _Retryable(Exception):
    pass


@dataclass
class LLMTrace:
    model: str
    stage: str = ""
    system: str = ""
    user: str = ""
    response: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    attempts: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


class BaseClient:
    name: str = "base"
    retry_pauses = (2, 6)  # 429/5xx: 2 повтора с паузой 2 и 6 c
    _lock = threading.Lock()  # бесплатный GigaChat: один запрос за раз

    def _complete(self, messages: list[dict], temperature: float, max_tokens: int,
                  schema: Optional[dict]) -> tuple[str, int, int]:
        raise NotImplementedError

    def _complete_with_retry(self, *args) -> tuple[str, int, int, int]:
        attempts = 0
        for pause in (*self.retry_pauses, None):
            attempts += 1
            try:
                with self._lock:
                    return (*self._complete(*args), attempts)
            except _Retryable as e:
                if pause is None:
                    raise LLMUnavailable(f"Модель недоступна после повторов: {e}") from e
                time.sleep(pause)
        raise LLMUnavailable("unreachable")  # pragma: no cover

    def chat_json(self, system: str, user: str, schema: Optional[dict] = None,
                  temperature: float = 0.1, max_tokens: int = 6000,
                  history: Optional[list[dict]] = None,
                  stage: str = "") -> tuple[dict, LLMTrace]:
        """Вернуть (dict, trace). history — предыдущие реплики user/assistant для повтора."""
        messages = [{"role": "system", "content": system}, *(history or []),
                    {"role": "user", "content": user}]
        t0 = time.time()
        text, pt, ct, attempts = self._complete_with_retry(messages, temperature, max_tokens, schema)
        trace = LLMTrace(model=self.name, stage=stage, system=system, user=user, response=text,
                         prompt_tokens=pt, completion_tokens=ct, attempts=attempts)
        try:
            data = extract_json(text)
        except JSONParseError as e:  # один повтор с текстом ошибки
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"Ответ не разобран как JSON ({e}). "
                                                     "Верни только валидный JSON-объект, без пояснений."}]
            text, pt2, ct2, a2 = self._complete_with_retry(messages, temperature, max_tokens, schema)
            trace.response, trace.prompt_tokens, trace.completion_tokens = text, trace.prompt_tokens + pt2, trace.completion_tokens + ct2
            trace.attempts += a2
            data = extract_json(text)  # если и сейчас плохо — JSONParseError наружу
        trace.latency_ms = int((time.time() - t0) * 1000)
        return data, trace


# ----------------------------------------------------------------------------- GigaChat
class GigaChatClient(BaseClient):
    def __init__(self, cfg: dict, profile: str = "gigachat"):
        self.name = f"{profile}:{cfg['model']}"
        self.model = cfg["model"]
        self.credentials = cfg.get("credentials") or ""
        self.scope = cfg.get("scope") or "GIGACHAT_API_PERS"
        self.auth_url = cfg["auth_url"]
        self.base_url = cfg["base_url"].rstrip("/")
        ca = cfg.get("ca_bundle") or ""
        verify_flag = str(cfg.get("verify_ssl", "true")).lower() not in ("false", "0", "no")
        self.verify = ca if ca else verify_flag
        self.timeout = 120.0
        self._token: str | None = None
        self._expires_at = 0.0
        if not self.credentials:
            raise LLMUnavailable("Не задан GIGACHAT_CREDENTIALS (ключ авторизации) в .env")

    def _get_token(self, force: bool = False) -> str:
        if self._token and not force and time.time() < self._expires_at - 60:
            return self._token
        try:
            r = httpx.post(
                self.auth_url,
                headers={"Authorization": f"Basic {self.credentials}", "RqUID": str(uuid.uuid4()),
                         "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                data={"scope": self.scope}, verify=self.verify, timeout=30)
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"Не удалось получить токен GigaChat: {e}. "
                                 "Проверьте сертификат Минцифры (GIGACHAT_CA_BUNDLE) и сеть.") from e
        if r.status_code != 200:
            raise LLMUnavailable(f"Авторизация GigaChat: HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        self._token = data["access_token"]
        self._expires_at = data.get("expires_at", 0) / 1000 or time.time() + 25 * 60
        return self._token

    def _complete(self, messages, temperature, max_tokens, schema):
        payload = {"model": self.model, "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens, "stream": False}
        for refreshed in (False, True):
            token = self._get_token(force=refreshed)
            try:
                r = httpx.post(f"{self.base_url}/chat/completions", json=payload,
                               headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                               verify=self.verify, timeout=self.timeout)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                raise _Retryable(str(e)) from e
            if r.status_code == 401 and not refreshed:
                continue  # токен протух — обновим и повторим
            break
        if r.status_code == 429 or r.status_code >= 500:
            raise _Retryable(f"HTTP {r.status_code}")
        if r.status_code != 200:
            raise LLMUnavailable(f"GigaChat HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        usage = data.get("usage", {})
        return (data["choices"][0]["message"]["content"] or "",
                usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))


# ----------------------------------------------------------------------------- OpenAI-compatible
class OpenAICompatClient(BaseClient):
    def __init__(self, cfg: dict, profile: str = "openai_compat"):
        from openai import OpenAI
        if not cfg.get("base_url") or not cfg.get("model"):
            raise LLMUnavailable(f"Профиль '{profile}': не заданы base_url/model (см. .env)")
        self.name = f"{profile}:{cfg['model']}"
        self.model = cfg["model"]
        self.structured = cfg.get("structured", "none")
        self.extra = cfg.get("extra") or {}
        self.client = OpenAI(base_url=cfg["base_url"], api_key=cfg.get("api_key") or "none", timeout=120.0,
                             max_retries=0)

    def _complete(self, messages, temperature, max_tokens, schema):
        import openai
        kwargs: dict = {"model": self.model, "messages": messages, "temperature": temperature,
                        "max_tokens": max_tokens}
        if self.structured == "json_schema" and schema:
            kwargs["response_format"] = {"type": "json_schema",
                                         "json_schema": {"name": "ProcessIR", "schema": schema, "strict": False}}
        elif self.structured in ("json_object", "json_schema"):
            kwargs["response_format"] = {"type": "json_object"}
        if self.extra:
            kwargs["extra_body"] = self.extra
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError) as e:
            raise _Retryable(str(e)) from e
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                raise _Retryable(str(e)) from e
            raise LLMUnavailable(f"HTTP {e.status_code}: {e}") from e
        u = resp.usage
        return (resp.choices[0].message.content or "",
                getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0)


def get_client(profile: str | None = None) -> BaseClient:
    name, cfg = resolve_profile(profile)
    provider = cfg.get("provider", "openai")
    if provider == "gigachat":
        return GigaChatClient(cfg, name)
    return OpenAICompatClient(cfg, name)
