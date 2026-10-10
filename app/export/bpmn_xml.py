"""M7: ProcessIR (dict) + layout -> BPMN 2.0 XML (lxml)."""
import re
from lxml import etree

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}
TAG = {
    "start": "startEvent", "end": "endEvent", "task": "task", "user_task": "userTask",
    "service_task": "serviceTask", "manual_task": "manualTask", "send_task": "sendTask",
    "receive_task": "receiveTask", "xor": "exclusiveGateway", "and": "parallelGateway",
    "or": "inclusiveGateway", "timer": "intermediateCatchEvent",
    "message_catch": "intermediateCatchEvent", "subprocess": "subProcess",
}
PREFIX = {"startEvent": "Event", "endEvent": "Event", "intermediateCatchEvent": "Event",
          "exclusiveGateway": "Gateway", "parallelGateway": "Gateway", "inclusiveGateway": "Gateway"}


def _q(p, t):
    return "{%s}%s" % (NS[p], t)


def _clean(s):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(s or ""))


def _bounds(parent, b):
    etree.SubElement(parent, _q("dc", "Bounds"), x=str(b["x"]), y=str(b["y"]),
                     width=str(b["w"]), height=str(b["h"]))


def to_xml(ir, layout):
    steps = {s["id"]: s for s in ir["steps"]}
    node_id, emap = {}, {}
    for n, (sid, s) in enumerate(steps.items(), 1):
        tag = TAG.get(s["type"], "task")
        node_id[sid] = f"{PREFIX.get(tag, 'Activity')}_{n}"
        emap[node_id[sid]] = sid
    edges = layout["edges"]
    flow_id = {e["i"]: f"Flow_{e['i'] + 1}" for e in edges}
    for e in edges:
        emap[flow_id[e["i"]]] = f"{e['src']}->{e['dst']}"

    root = etree.Element(_q("bpmn", "definitions"), nsmap={k: v for k, v in NS.items()},
                         id="Definitions_1", targetNamespace="http://bpmn.io/schema/bpmn")
    collab = etree.SubElement(root, _q("bpmn", "collaboration"), id="Collaboration_1")
    pname = _clean((ir.get("process") or {}).get("name")) or "Процесс"
    etree.SubElement(collab, _q("bpmn", "participant"), id="Participant_1", name=pname, processRef="Process_1")
    proc = etree.SubElement(root, _q("bpmn", "process"), id="Process_1", isExecutable="false")

    lane_ids = {l: f"Lane_{k}" for k, l in enumerate(layout["lane_order"], 1)}
    laneset = etree.SubElement(proc, _q("bpmn", "laneSet"), id="LaneSet_1")
    for l in layout["lane_order"]:
        lane = etree.SubElement(laneset, _q("bpmn", "lane"), id=lane_ids[l], name=_clean(layout["lane_names"][l]))
        for sid in steps:
            if layout["lane_of"][sid] == l:
                etree.SubElement(lane, _q("bpmn", "flowNodeRef")).text = node_id[sid]

    default_of = {e["src"]: flow_id[e["i"]] for e in edges if e["default"]}
    for sid, s in steps.items():
        tag = TAG.get(s["type"], "task")
        el = etree.SubElement(proc, _q("bpmn", tag), id=node_id[sid])
        if s.get("name"):
            el.set("name", _clean(s["name"]))
        if tag in ("exclusiveGateway", "inclusiveGateway") and sid in default_of:
            el.set("default", default_of[sid])
        for e in edges:
            if e["dst"] == sid:
                etree.SubElement(el, _q("bpmn", "incoming")).text = flow_id[e["i"]]
        for e in edges:
            if e["src"] == sid:
                etree.SubElement(el, _q("bpmn", "outgoing")).text = flow_id[e["i"]]
        if s["type"] == "timer":
            etree.SubElement(el, _q("bpmn", "timerEventDefinition"))
        elif s["type"] == "message_catch":
            etree.SubElement(el, _q("bpmn", "messageEventDefinition"))

    for e in edges:
        f = etree.SubElement(proc, _q("bpmn", "sequenceFlow"), id=flow_id[e["i"]],
                             sourceRef=node_id[e["src"]], targetRef=node_id[e["dst"]])
        if e["label"]:
            f.set("name", _clean(e["label"]))

    diagram = etree.SubElement(root, _q("bpmndi", "BPMNDiagram"), id="BPMNDiagram_1")
    plane = etree.SubElement(diagram, _q("bpmndi", "BPMNPlane"), id="BPMNPlane_1", bpmnElement="Collaboration_1")

    sh = etree.SubElement(plane, _q("bpmndi", "BPMNShape"), id="Participant_1_di",
                          bpmnElement="Participant_1", isHorizontal="true")
    _bounds(sh, layout["pool"])
    for l in layout["lane_order"]:
        sh = etree.SubElement(plane, _q("bpmndi", "BPMNShape"), id=f"{lane_ids[l]}_di",
                              bpmnElement=lane_ids[l], isHorizontal="true")
        _bounds(sh, layout["lanes"][l])
    for sid, s in steps.items():
        b = layout["shapes"][sid]
        sh = etree.SubElement(plane, _q("bpmndi", "BPMNShape"), id=f"{node_id[sid]}_di", bpmnElement=node_id[sid])
        if s["type"] == "xor":
            sh.set("isMarkerVisible", "true")
        _bounds(sh, b)
        if s.get("name") and (s["type"] in ("start", "end", "timer", "message_catch", "xor", "and", "or")):
            lb = etree.SubElement(sh, _q("bpmndi", "BPMNLabel"))
            if s["type"] in ("xor", "and", "or"):
                _bounds(lb, {"x": b["cx"] - 50, "y": b["y"] - 30, "w": 100, "h": 27})
            else:
                _bounds(lb, {"x": b["cx"] - 50, "y": b["y"] + b["h"] + 4, "w": 100, "h": 27})
    for e in edges:
        ed = etree.SubElement(plane, _q("bpmndi", "BPMNEdge"), id=f"{flow_id[e['i']]}_di", bpmnElement=flow_id[e["i"]])
        for x, y in e["points"]:
            etree.SubElement(ed, _q("di", "waypoint"), x=str(x), y=str(y))
        if e["label_bounds"]:
            _bounds(etree.SubElement(ed, _q("bpmndi", "BPMNLabel")), e["label_bounds"])

    xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True).decode("utf-8")
    return xml, emap
