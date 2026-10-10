"""M2. Извлечение: пронумерованный текст -> ProcessIR (один вызов LLM в MVP)."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.llm.client import BaseClient, LLMTrace
from app.model.ir import ProcessIR

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


def _load_fewshot(n: int) -> tuple[str, str]:
    fs = PROMPTS / "fewshot"
    inp = (fs / f"{n:02d}_input.txt").read_text(encoding="utf-8").strip()
    out = json.dumps(
        json.loads((fs / f"{n:02d}_output.json").read_text(encoding="utf-8")),
        ensure_ascii=False,
    )
    return inp, out


def build_system_prompt() -> str:
    tpl = (PROMPTS / "flow.md").read_text(encoding="utf-8")
    for n in (1, 2):
        inp, out = _load_fewshot(n)
        tpl = tpl.replace(f"{{fewshot_input{n}}}", inp).replace(f"{{fewshot_output{n}}}", out)
    return tpl

def extract_ir(client: BaseClient, numbered_text: str) -> tuple[ProcessIR, list[LLMTrace]]:
    """Вызвать модель и провалидировать. При ошибке схемы — один повтор с текстом ошибки."""
    system = build_system_prompt()
    user = f"Текст процесса:\n{numbered_text}\n\nВерни JSON."
    traces: list[LLMTrace] = []
    data, trace = client.chat_json(system, user, schema=ProcessIR.model_json_schema(), stage="extract")
    traces.append(trace)
    try:
        return ProcessIR.model_validate(data), traces
    except ValidationError as e:
        history = [{"role": "user", "content": user}, {"role": "assistant", "content": trace.response}]
        retry = f"JSON не соответствует схеме: {str(e)[:600]}\nИсправь и верни JSON целиком."
        data, trace2 = client.chat_json(system, retry, schema=ProcessIR.model_json_schema(),
                                        history=history, stage="extract_retry")
        traces.append(trace2)
        return ProcessIR.model_validate(data), traces  # повторная ошибка уйдёт вызывающему
