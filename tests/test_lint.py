import json
from pathlib import Path

import pytest

from app.lint import lint
from app.model.ir import ProcessIR

FS = Path(__file__).resolve().parent.parent / "app" / "prompts" / "fewshot" / "01_output.json"


def mk(steps, participants=("P1", "P2")):
    return ProcessIR.model_validate({
        "process": {"name": "t"},
        "participants": [{"id": p, "name": f"Участник {p}"} for p in participants],
        "steps": steps})


def codes(issues):
    return [i.code for i in issues]


def check_clean(ir):
    """Структурные инварианты, нужные раскладке и XML."""
    sm = ir.step_map()
    pids = {p.id for p in ir.participants}
    assert any(s.type == "start" for s in ir.steps)
    inc = {s.id: 0 for s in ir.steps}
    for s in ir.steps:
        assert s.participant in pids
        if s.type == "end":
            assert not s.next
        else:
            assert s.next, f"тупик {s.id}"
        for e in s.next:
            assert e.to in sm and e.to != s.id
            inc[e.to] += 1
        if s.type in ("xor", "or") and s.origin == "llm":
            assert len(s.next) >= 2
        if not s.is_gateway and s.type != "end":
            assert len(s.next) == 1, f"неявное ветвление {s.id}"
    for s in ir.steps:
        if not s.is_gateway and s.type != "start":
            assert inc[s.id] <= 1, f"неявное слияние {s.id}"


def test_fewshot_gets_only_merge():
    ir = ProcessIR.model_validate(json.loads(FS.read_text(encoding="utf-8")))
    out, issues = lint(ir)
    assert codes(issues) == ["L07"]
    merge = [s for s in out.steps if s.origin == "autofix"][0]
    assert merge.type == "and"       # тип слияния = тип разветвления
    check_clean(out)


def test_input_not_mutated():
    ir = mk([{"id": "S1", "type": "task", "participant": "P1", "next": []}])
    lint(ir)
    assert ir.steps[0].next == [] and len(ir.steps) == 1


def test_L05_L06_missing_start_and_dead_end():
    ir = mk([{"id": "S1", "type": "task", "name": "Отправить акт", "participant": "P1", "src": [7],
              "next": [{"to": "S2"}]},
             {"id": "S2", "type": "task", "name": "Подписать", "participant": "P2", "src": [8]}])
    out, issues = lint(ir)
    assert "L05" in codes(issues) and "L06" in codes(issues)
    msg = [i for i in issues if i.code == "L06"][0]
    assert "Подписать" in msg.message and "8" in msg.message
    check_clean(out)


def test_L01_unknown_refs():
    ir = mk([{"id": "S1", "type": "start", "participant": "PX", "next": [{"to": "S2"}, {"to": "NOPE"}]},
             {"id": "S2", "type": "task", "participant": "P2", "next": [{"to": "E"}]},
             {"id": "E", "type": "end", "participant": "P1"}])
    out, issues = lint(ir)
    assert [i.severity for i in issues if i.code == "L01"].count("error") == 1
    assert out.step_map()["S1"].participant in {"P1", "P2"}
    check_clean(out)


def test_L02_L03():
    ir = mk([{"id": "S1", "type": "start", "participant": "P1", "next": [{"to": "G"}]},
             {"id": "G", "type": "xor", "name": "Ок?", "participant": "P1", "next": [{"to": "S2", "label": "Да"}]},
             {"id": "S2", "type": "task", "participant": "P2", "next": [{"to": "S2"}, {"to": "E"}]},
             {"id": "E", "type": "end", "participant": "P2"}])
    out, issues = lint(ir)
    assert {"L02", "L03"} <= set(codes(issues))
    assert "G" not in out.step_map()
    check_clean(out)


def test_L04_implicit_split():
    ir = mk([{"id": "S1", "type": "start", "participant": "P1", "next": [{"to": "S2"}]},
             {"id": "S2", "type": "task", "participant": "P1", "next": [{"to": "A"}, {"to": "B"}]},
             {"id": "A", "type": "end", "participant": "P1"}, {"id": "B", "type": "end", "participant": "P2"}])
    out, issues = lint(ir)
    assert "L04" in codes(issues)
    gw = [s for s in out.steps if s.origin == "autofix"][0]
    assert gw.type == "and"
    check_clean(out)


def test_L07_loop_merge_is_xor():
    ir = mk([{"id": "S1", "type": "start", "participant": "P1", "next": [{"to": "S2"}]},
             {"id": "S2", "type": "task", "participant": "P1", "next": [{"to": "G"}]},
             {"id": "G", "type": "xor", "name": "Ок?", "participant": "P2",
              "next": [{"to": "E", "label": "Да"}, {"to": "S2", "label": "Нет"}]},
             {"id": "E", "type": "end", "participant": "P2"}])
    out, issues = lint(ir)
    assert codes(issues) == ["L07"]
    assert [s for s in out.steps if s.origin == "autofix"][0].type == "xor"
    check_clean(out)


def test_L11_empty_lane():
    ir = mk([{"id": "S1", "type": "start", "participant": "P1", "next": [{"to": "E"}]},
             {"id": "E", "type": "end", "participant": "P1"}])
    out, issues = lint(ir)
    assert codes(issues) == ["L11"] and [p.id for p in out.participants] == ["P1"]


def test_empty_steps_is_error():
    out, issues = lint(mk([]))
    assert issues[0].severity == "error"


def test_idempotent():
    ir = ProcessIR.model_validate(json.loads(FS.read_text(encoding="utf-8")))
    once, _ = lint(ir)
    twice, issues = lint(once)
    assert issues == [] and twice == once


def test_lenient_llm_shapes():
    ir = ProcessIR.model_validate({
        "process": "Тест", "participants": [{"id": "P1", "name": "A", "kind": "что-то"}],
        "steps": [{"id": "S1", "type": "Exclusive Gateway", "name": "x", "participant": "P1",
                   "next": ["S2", {"to": "S3", "label": " Да "}], "src": ["[3]", 4]},
                  {"id": "S2", "type": "UserTask"}, {"id": "S3", "type": "unknown"}]})
    s = ir.steps[0]
    assert s.type == "xor" and s.next[0].to == "S2" and s.next[1].label == "Да" and s.src == [3, 4]
    assert ir.steps[1].type == "user_task" and ir.steps[2].type == "task"
