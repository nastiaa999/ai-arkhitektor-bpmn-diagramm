"""M2 на фейковой модели (без сети)."""
import json
from pathlib import Path

from app.llm.client import BaseClient
from app.pipeline.extract import build_system_prompt, extract_ir
from app.pipeline.orchestrator import build_ir
from app.pipeline.preprocess import numbered, split_sentences

FS = Path(__file__).resolve().parent.parent / "app" / "prompts" / "fewshot"


class Fake(BaseClient):
    name = "fake"
    retry_pauses = ()

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def _complete(self, messages, temperature, max_tokens, schema):
        self.calls.append(messages)
        return self.replies.pop(0), 10, 10


GOOD = (FS / "01_output.json").read_text(encoding="utf-8")


def test_prompt_contains_example_and_rules():
    p = build_system_prompt()
    assert "{fewshot" not in p and "Не выдумывай" in p and "Заказ отменён" in p


def test_sentences():
    # пункт списка = одно предложение; обычный абзац режется razdel с учётом сокращений
    s, w = split_sentences("1. Клиент пишет заявку.\n2. Менеджер проверяет заявку. Затем звонит.\n"
                           "Потом всё, т.е. конец. Готово.")
    assert [x.n for x in s] == [1, 2, 3, 4]
    assert s[0].text == "Клиент пишет заявку."
    assert s[2].text == "Потом всё, т.е. конец."
    assert numbered(s).startswith("[1] Клиент")


def test_extract_ok_with_noise():
    c = Fake(["<think>...</think>```json\n" + GOOD + "\n```"])
    ir, tr = extract_ir(c, "[1] x")
    assert len(ir.steps) == 12 and len(tr) == 1


def test_json_retry():
    c = Fake(["не json вообще", GOOD])
    ir, tr = extract_ir(c, "[1] x")
    assert len(ir.steps) == 12 and len(c.calls) == 2


def test_build_ir_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr("app.pipeline.orchestrator.runs_dir", lambda: tmp_path)
    res = build_ir("Клиент оформляет заказ.", client=Fake([GOOD]))
    assert res.llm_calls == 1 and [i.code for i in res.issues] == ["L07"]
    assert (res.run_dir / "ir_final.json").exists()
    assert json.loads((res.run_dir / "issues.json").read_text(encoding="utf-8"))[0]["code"] == "L07"
