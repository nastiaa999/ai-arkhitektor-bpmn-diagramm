from dataclasses import asdict, is_dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.export.pipeline import build_diagram
from app.pipeline.orchestrator import build_ir
from app.validate.xsd import validate_xsd

app = FastAPI(title="BPMN-архитектор")


def _d(o):
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    if is_dataclass(o):
        return asdict(o)
    return o


class GenerateReq(BaseModel):
    text: str
    model: str | None = None


class ValidateReq(BaseModel):
    xml: str


@app.post("/api/generate")
def generate(req: GenerateReq):
    if not req.text.strip():
        raise HTTPException(422, "Пустой текст")
    try:
        res = build_ir(req.text, model=req.model)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(502, f"Ошибка LLM: {e}")
    ir = _d(res.ir)
    try:
        diagram = build_diagram(ir)
    except Exception as e:
        raise HTTPException(500, f"Ошибка построения диаграммы: {e}")
    return {
        "bpmn_xml": diagram["bpmn_xml"],
        "element_map": diagram["element_map"],
        "ir": ir,
        "issues": [_d(i) for i in res.issues],
        "sentences": [_d(s) for s in res.sentences],
        "validation": {"xsd": validate_xsd(diagram["bpmn_xml"])},
        "metrics": diagram["metrics"],
        "clarifications": [_d(c) for c in getattr(res, "clarifications", [])],
    }


@app.post("/api/validate")
def validate(req: ValidateReq):
    return {"xsd": validate_xsd(req.xml)}


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "web", html=True), name="web")
