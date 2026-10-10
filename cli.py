#!/usr/bin/env python
"""CLI: текст процесса -> IR (+ .bpmn, когда подключён экспорт Человека 2).

  python cli.py generate examples/inputs/02_purchase.txt -o out/02.json --model gigachat
  python cli.py batch examples/inputs/ -o out/
  python cli.py ping                      # проверка подключения к модели
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _to_bpmn(ir):
    """Подключение Человека 2: функция ir_to_bpmn(ProcessIR) -> str (раскладка + XML)."""
    try:
        from app.export.pipeline import ir_to_bpmn  # type: ignore
    except ImportError:
        return None
    return ir_to_bpmn(ir)


def _run_one(src: Path, out: Path, model: str | None) -> bool:
    from app.llm.client import LLMError
    from app.pipeline.orchestrator import build_ir
    try:
        res = build_ir(src.read_text(encoding="utf-8"), model=model)
    except LLMError as e:
        print(f"[{src.name}] ОШИБКА LLM: {e}", file=sys.stderr)
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    stem = out.with_suffix("")
    stem.with_suffix(".ir.json").write_text(json.dumps(res.ir.model_dump(), ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    stem.with_suffix(".issues.json").write_text(
        json.dumps([i.model_dump() for i in res.issues], ensure_ascii=False, indent=2), encoding="utf-8")
    xml = _to_bpmn(res.ir)
    if xml and out.suffix == ".bpmn":
        out.write_text(xml, encoding="utf-8")
    elif out.suffix == ".bpmn":
        print("  (экспорт BPMN ещё не подключён — сохранён только IR)")
    n = {s: sum(1 for i in res.issues if i.severity == s) for s in ("error", "warning", "info")}
    print(f"[{src.name}] {res.model}: шагов {len(res.ir.steps)}, участников {len(res.ir.participants)}, "
          f"замечаний E{n['error']}/W{n['warning']}/I{n['info']}, {res.latency_ms['total']} мс  -> {stem}.*")
    for i in res.issues:
        if i.severity != "info":
            print(f"    {i.code} {i.severity}: {i.message}")
    return n["error"] == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="BPMN-архитектор: текст -> IR/BPMN")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate"); g.add_argument("input"); g.add_argument("-o", "--out", required=True)
    g.add_argument("--model")
    b = sub.add_parser("batch"); b.add_argument("dir"); b.add_argument("-o", "--out", required=True)
    b.add_argument("--model"); b.add_argument("--ext", default=".bpmn")
    p = sub.add_parser("ping"); p.add_argument("--model")
    a = ap.parse_args()

    if a.cmd == "ping":
        from app.llm.client import get_client
        c = get_client(a.model)
        data, tr = c.chat_json("Отвечай только JSON.", 'Верни {"ok": true, "msg": "привет"}')
        print(c.name, "->", data, f"({tr.latency_ms} мс)")
        return 0
    if a.cmd == "generate":
        return 0 if _run_one(Path(a.input), Path(a.out), a.model) else 1
    ok = True
    for f in sorted(Path(a.dir).glob("*.txt")):
        ok &= _run_one(f, Path(a.out) / (f.stem + a.ext), a.model)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
