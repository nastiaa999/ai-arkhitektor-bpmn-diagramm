"""M9 (часть Человека 1): текст -> (ProcessIR, issues). Дальше подключается раскладка/XML Человека 2.

Контракт для Человека 2:
    from app.pipeline.orchestrator import build_ir
    res = build_ir(text, model=None)        # res.ir — чистый ProcessIR, res.issues — замечания
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.config import runs_dir
from app.lint import lint
from app.llm.client import BaseClient, get_client
from app.model.ir import Issue, ProcessIR, Sentence
from app.pipeline.extract import extract_ir
from app.pipeline.preprocess import numbered, split_sentences
from app.lint.clarify import issues_to_questions

@dataclass
class IRResult:
    run_id: str
    ir: ProcessIR
    ir_raw: ProcessIR
    issues: list[Issue]
    sentences: list[Sentence]
    warnings: list[str] = field(default_factory=list)
    model: str = ""
    latency_ms: dict = field(default_factory=dict)
    llm_calls: int = 0
    run_dir: Path | None = None
    clarifications: list[dict] = field(default_factory=list)


def build_ir(text: str, model: str | None = None, client: BaseClient | None = None,
             save: bool = True) -> IRResult:
    t0 = time.time()
    run_id = f"{datetime.now():%Y-%m-%dT%H-%M-%S}_{uuid4().hex[:4]}"
    sentences, warnings = split_sentences(text)
    client = client or get_client(model)

    t1 = time.time()
    ir_raw, traces = extract_ir(client, numbered(sentences))
    t_llm = int((time.time() - t1) * 1000)

    ir, issues = lint(ir_raw)
    clarifications = issues_to_questions(issues, ir)
    res = IRResult(run_id=run_id, ir=ir, ir_raw=ir_raw, issues=issues, sentences=sentences, clarifications=clarifications,
                   warnings=warnings, model=client.name,
                   latency_ms={"llm": t_llm, "total": int((time.time() - t0) * 1000)},
                   llm_calls=len(traces))
    if save:
        d = runs_dir() / run_id
        d.mkdir(parents=True, exist_ok=True)
        res.run_dir = d
        dump = lambda name, obj: (d / name).write_text(  # noqa: E731
            json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "input.txt").write_text(text, encoding="utf-8")
        dump("sentences.json", [s.model_dump() for s in sentences])
        for i, t in enumerate(traces):
            dump(f"llm_{i}_{t.stage}.json", t.to_dict())
        dump("ir_raw.json", ir_raw.model_dump())
        dump("ir_final.json", ir.model_dump())
        dump("issues.json", [i.model_dump() for i in issues])
    return res
