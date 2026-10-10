"""Контракт IR (ProcessIR). Единственный формат обмена между модулями.

Валидаторы намеренно «мягкие»: слабые модели путают названия типов и формат next,
а строгость мы обеспечиваем линтером (M3), а не отказом на входе.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ParticipantKind = Literal["role", "department", "system", "external"]
ArtifactKind = Literal["document", "data_store"]
StepType = Literal[
    "start", "end", "task", "user_task", "service_task", "manual_task",
    "send_task", "receive_task", "xor", "and", "or",
    "timer", "message_catch", "subprocess",  # P2
]
GATEWAYS = {"xor", "and", "or"}

_TYPE_ALIASES = {
    "exclusive_gateway": "xor", "exclusivegateway": "xor", "gateway": "xor", "exclusive": "xor",
    "parallel_gateway": "and", "parallelgateway": "and", "parallel": "and",
    "inclusive_gateway": "or", "inclusivegateway": "or", "inclusive": "or",
    "start_event": "start", "startevent": "start", "begin": "start",
    "end_event": "end", "endevent": "end", "finish": "end",
    "usertask": "user_task", "servicetask": "service_task", "manualtask": "manual_task",
    "sendtask": "send_task", "receivetask": "receive_task", "user": "user_task",
    "service": "service_task", "action": "task", "activity": "task",
}


class Process(BaseModel):
    name: str = "Процесс"
    goal: str = ""


class Participant(BaseModel):
    id: str
    name: str
    kind: ParticipantKind = "role"

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v):
        v = str(v or "role").strip().lower()
        return v if v in ("role", "department", "system", "external") else "role"


class Artifact(BaseModel):
    id: str
    name: str
    kind: ArtifactKind = "document"

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v):
        v = str(v or "document").strip().lower()
        return v if v in ("document", "data_store") else "document"


class Edge(BaseModel):
    to: str
    label: Optional[str] = None
    default: bool = False

    @field_validator("label", mode="before")
    @classmethod
    def _label(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        return v or None


class Step(BaseModel):
    id: str
    type: StepType = "task"
    name: str = ""
    participant: str = ""
    src: list[int] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    next: list[Edge] = Field(default_factory=list)
    origin: Literal["llm", "autofix"] = "llm"

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, v):
        key = str(v or "task").strip().lower().replace("-", "_").replace(" ", "_")
        key = _TYPE_ALIASES.get(key, key)
        allowed = StepType.__args__  # type: ignore[attr-defined]
        return key if key in allowed else "task"

    @field_validator("name", "participant", mode="before")
    @classmethod
    def _str(cls, v):
        return "" if v is None else str(v).strip()

    @field_validator("src", mode="before")
    @classmethod
    def _src(cls, v):
        if v is None:
            return []
        if not isinstance(v, list):
            v = [v]
        out = []
        for x in v:
            try:
                out.append(int(str(x).strip("[] ")))
            except ValueError:
                pass
        return out

    @field_validator("inputs", "outputs", mode="before")
    @classmethod
    def _ids(cls, v):
        if v is None:
            return []
        return [str(x) for x in (v if isinstance(v, list) else [v])]

    @field_validator("next", mode="before")
    @classmethod
    def _next(cls, v):
        if v is None:
            return []
        if isinstance(v, (str, dict)):
            v = [v]
        return [{"to": e} if isinstance(e, str) else e for e in v]

    @property
    def is_gateway(self) -> bool:
        return self.type in GATEWAYS


class ProcessIR(BaseModel):
    process: Process = Field(default_factory=Process)
    participants: list[Participant] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)

    @field_validator("process", mode="before")
    @classmethod
    def _process(cls, v):
        if v is None:
            return {}
        if isinstance(v, str):
            return {"name": v}
        return v

    def step_map(self) -> dict[str, Step]:
        return {s.id: s for s in self.steps}

    def participant_map(self) -> dict[str, Participant]:
        return {p.id: p for p in self.participants}


class Issue(BaseModel):
    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    step_ids: list[str] = Field(default_factory=list)
    src: list[int] = Field(default_factory=list)
    autofixed: bool = False


class Sentence(BaseModel):
    n: int
    text: str
