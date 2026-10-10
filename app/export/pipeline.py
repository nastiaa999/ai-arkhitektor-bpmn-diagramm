"""Точка входа для CLI и API: ProcessIR -> BPMN."""
from app.layout.engine import compute_layout
from app.export.bpmn_xml import to_xml


def _as_dict(ir):
    return ir.model_dump(mode="json") if hasattr(ir, "model_dump") else ir


def build_diagram(ir) -> dict:
    d = _as_dict(ir)
    layout = compute_layout(d)
    xml, element_map = to_xml(d, layout)
    return {"bpmn_xml": xml, "element_map": element_map, "metrics": layout["metrics"]}


def ir_to_bpmn(ir) -> str:
    return build_diagram(ir)["bpmn_xml"]
