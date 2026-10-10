"""M3. Линтер логики процесса с автоисправлением.

Правила применяются строго по порядку: L01, L02, L03, L04, L05, L06, L07, L09, L08, L10, L11.
Все добавленные элементы получают origin="autofix".
"""
from __future__ import annotations

import copy

import networkx as nx

from app.model.ir import Edge, Issue, ProcessIR, Step

ROOT = "__root__"


class _Ctx:
    def __init__(self, ir: ProcessIR):
        self.ir = ir
        self.issues: list[Issue] = []
        self._n = 0

    def new_id(self, prefix: str) -> str:
        used = {s.id for s in self.ir.steps}
        while True:
            self._n += 1
            cand = f"{prefix}{self._n}"
            if cand not in used:
                return cand

    def add(self, code, severity, message, step_ids=(), src=(), autofixed=False):
        self.issues.append(Issue(code=code, severity=severity, message=message,
                                 step_ids=list(step_ids), src=sorted(set(src)), autofixed=autofixed))

    def graph(self) -> nx.DiGraph:
        g = nx.DiGraph()
        for s in self.ir.steps:
            g.add_node(s.id)
        for s in self.ir.steps:
            for e in s.next:
                if e.to in g:
                    g.add_edge(s.id, e.to)
        return g

    def preds(self) -> dict[str, list[Step]]:
        m: dict[str, list[Step]] = {s.id: [] for s in self.ir.steps}
        for s in self.ir.steps:
            for e in s.next:
                if e.to in m:
                    m[e.to].append(s)
        return m

    def incoming_count(self) -> dict[str, int]:
        m = {s.id: 0 for s in self.ir.steps}
        for s in self.ir.steps:
            for e in s.next:
                if e.to in m:
                    m[e.to] += 1
        return m


def _q(name: str) -> str:
    return f"«{name}»" if name else "(без названия)"


def _insert_step(ctx: _Ctx, **kw) -> Step:
    st = Step(origin="autofix", **kw)
    ctx.ir.steps.append(st)
    return st


# --------------------------------------------------------------------------- правила
def l01_references(ctx: _Ctx) -> None:
    ir = ctx.ir
    if not ir.participants:
        from app.model.ir import Participant
        ir.participants.append(Participant(id="P1", name="Исполнитель"))
        ctx.add("L01", "warning", "В тексте не найдены участники — добавлен «Исполнитель»", autofixed=True)
    pids = {p.id for p in ir.participants}
    sids = {s.id for s in ir.steps}
    aids = {a.id for a in ir.artifacts}
    preds = ctx.preds()
    seen: set[str] = set()
    sys_pid = None
    for s in ir.steps:
        if s.participant not in pids:
            if s.type == "service_task":
                # автоматический шаг — не тащим сюда участника-человека из соседнего шага
                if sys_pid is None:
                    existing = next((p.id for p in ir.participants
                                      if any(k in p.name.lower() for k in ("систем", "сервис", "1с", "упп"))), None)
                    if existing:
                        sys_pid = existing
                    else:
                        from app.model.ir import Participant
                        sys_pid = ctx.new_id("SYS")
                        ir.participants.append(Participant(id=sys_pid, name="Информационная система"))
                        pids.add(sys_pid)
                s.participant = sys_pid
            else:
                prev = next((p.participant for p in preds.get(s.id, []) if p.participant in pids), None)
                s.participant = prev or ir.participants[0].id
            ctx.add("L01", "warning", f"У шага {_q(s.name)} не определён участник — назначен "
                    f"«{ir.participant_map()[s.participant].name}»", [s.id], s.src, True)
        bad = [e for e in s.next if e.to not in sids]
        if bad:
            s.next = [e for e in s.next if e.to in sids]
            ctx.add("L01", "error", f"Шаг {_q(s.name)} ссылается на несуществующий шаг "
                    f"({', '.join(e.to for e in bad)}) — связь удалена", [s.id], s.src, True)
        s.inputs = [a for a in s.inputs if a in aids]
        s.outputs = [a for a in s.outputs if a in aids]

def l02_self_loops(ctx: _Ctx) -> None:
    for s in ctx.ir.steps:
        n = len(s.next)
        s.next = [e for e in s.next if e.to != s.id]
        if len(s.next) != n:
            ctx.add("L02", "warning", f"Шаг {_q(s.name)} ссылался сам на себя — связь удалена", [s.id], s.src, True)


def l03_trivial_gateways(ctx: _Ctx) -> None:
    changed = True
    while changed:
        changed = False
        for gw in list(ctx.ir.steps):
            if gw.type not in ("xor", "or") or len(gw.next) > 1:
                continue
            target = gw.next[0].to if gw.next else None
            for p in ctx.preds()[gw.id]:
                new_next = []
                for e in p.next:
                    if e.to != gw.id:
                        new_next.append(e)
                    elif target and all(x.to != target for x in p.next):
                        new_next.append(Edge(to=target, label=e.label, default=e.default))
                p.next = new_next
            ctx.ir.steps.remove(gw)
            ctx.add("L03", "warning", f"Шлюз {_q(gw.name)} имел меньше двух выходов — удалён", [gw.id], gw.src, True)
            changed = True
            break


def l04_implicit_split(ctx: _Ctx) -> None:
    for s in list(ctx.ir.steps):
        if s.is_gateway or s.type == "end" or len(s.next) < 2:
            continue
        labeled = any(e.label for e in s.next)
        gtype = "xor" if labeled else "and"
        gw = _insert_step(ctx, id=ctx.new_id("G"), type=gtype,
                          name="Результат?" if labeled else "Параллельные действия",
                          participant=s.participant, src=list(s.src), next=s.next)
        s.next = [Edge(to=gw.id)]
        ctx.add("L04", "info", f"После шага {_q(s.name)} несколько выходов — добавлен шлюз "
                f"{'исключающий' if labeled else 'параллельный'}", [s.id, gw.id], s.src, True)


def l05_start(ctx: _Ctx) -> None:
    if any(s.type == "start" for s in ctx.ir.steps) or not ctx.ir.steps:
        return
    inc = ctx.incoming_count()
    first = next((s for s in ctx.ir.steps if inc[s.id] == 0), ctx.ir.steps[0])
    st = _insert_step(ctx, id=ctx.new_id("ST"), type="start", name="Начало процесса",
                      participant=first.participant, src=[], next=[Edge(to=first.id)])
    ctx.ir.steps.insert(0, ctx.ir.steps.pop())  # старт — первым
    ctx.add("L05", "warning", f"Не найдено начало процесса — добавлено перед шагом {_q(first.name)}",
            [st.id, first.id], first.src, True)


def l06_dead_ends(ctx: _Ctx) -> None:
    for s in list(ctx.ir.steps):
        if s.type == "end" or s.next:
            continue
        end = _insert_step(ctx, id=ctx.new_id("E"), type="end", name="Процесс завершён",
                           participant=s.participant, src=[], next=[])
        s.next = [Edge(to=end.id)]
        where = f" (предл. {', '.join(map(str, s.src))})" if s.src else ""
        ctx.add("L06", "warning", f"Логический обрыв после {_q(s.name)}{where}: дальнейшие шаги не описаны. добавлен End «Процесс завершён»",
                [s.id, end.id], s.src, True)


def _merge_type(ctx: _Ctx, node_id: str) -> str:
    """Тип слияния = тип ближайшего доминирующего шлюза; по умолчанию xor."""
    g = ctx.graph()
    entries = [n for n, d in g.in_degree() if d == 0] or [ctx.ir.steps[0].id]
    g.add_node(ROOT)
    for n in entries:
        g.add_edge(ROOT, n)
    idom = nx.immediate_dominators(g, ROOT)
    sm = ctx.ir.step_map()
    cur = idom.get(node_id)
    while cur and cur != ROOT:
        st = sm.get(cur)
        if st and st.is_gateway:
            return st.type
        cur = idom.get(cur)
    return "xor"


def l07_implicit_merge(ctx: _Ctx) -> None:
    for s in list(ctx.ir.steps):
        if s.is_gateway or s.type == "start":
            continue
        preds = [p for p in ctx.preds()[s.id]]
        n_in = sum(1 for p in ctx.ir.steps for e in p.next if e.to == s.id)
        if n_in < 2:
            continue
        gtype = _merge_type(ctx, s.id)
        gw = _insert_step(ctx, id=ctx.new_id("M"), type=gtype, name="", participant=s.participant,
                          src=list(s.src), next=[Edge(to=s.id)])
        for p in preds:
            for e in p.next:
                if e.to == s.id and p is not gw:
                    e.to = gw.id
        label = {"xor": "исключающее", "and": "параллельное", "or": "включающее"}[gtype]
        ctx.add("L07", "info", f"В шаг {_q(s.name)} сходятся несколько веток — добавлено {label} слияние",
                [s.id, gw.id], s.src, True)

def l09_orphan_branches(ctx: _Ctx) -> None:
    """Шаг без единого входящего потока никогда не появится в схеме связанным —
    он просто зависает в воздухе (как случилось с «Уведомление об отказе» в тесте
    про закупку). Чаще всего это пропущенная альтернативная ветка решения
    («иначе» / «отказ»), которую модель создала как шаг, но не подключила
    к шлюзу. Подключаем её как default-ветку ближайшего по тексту (src)
    xor/or-шлюза, у которого такой ветки ещё нет."""
    inc = ctx.incoming_count()
    gateways = [s for s in ctx.ir.steps if s.type in ("xor", "or")]
    for s in list(ctx.ir.steps):
        if s.type == "start" or inc.get(s.id, 0) > 0:
            continue
        s_min_src = min(s.src) if s.src else None
        best, best_src = None, -1
        for gw in gateways:
            if any(e.to == s.id for e in gw.next):
                continue
            if any(e.default for e in gw.next):
                continue  # у шлюза уже есть ветка "иначе" — не трогаем
            gw_max_src = max(gw.src) if gw.src else -1
            if s_min_src is not None and gw_max_src >= s_min_src:
                continue  # шлюз описан позже этого шага — не подходит
            if gw_max_src > best_src:
                best_src, best = gw_max_src, gw
        if best is None:
            continue
        new_edge = Edge(to=s.id, label="Не согласовано", default=True)
        others = [e for e in best.next if not e.label]
        if len(others) == 1:
            others[0].label = "Согласовано"
        best.next.append(new_edge)
        ctx.add("L09", "warning",
                f"Шаг {_q(s.name)} был не подключён к схеме — добавлена ветка «Иначе» "
                f"от шлюза {_q(best.name)}", [best.id, s.id], s.src, True)
        
def l08_unreachable(ctx: _Ctx) -> None:
    g = ctx.graph()
    starts = [s.id for s in ctx.ir.steps if s.type == "start"]
    reach: set[str] = set()
    for st in starts:
        reach |= nx.descendants(g, st) | {st}
    for s in ctx.ir.steps:
        if s.id not in reach and starts:
            ctx.add("L08", "warning", f"Шаг {_q(s.name)} недостижим от начала процесса", [s.id], s.src)


def l10_unlabeled(ctx: _Ctx) -> None:
    for s in ctx.ir.steps:
        if s.type in ("xor", "or") and len(s.next) > 1:
            missing = [e for e in s.next if not e.label]
            if len(missing) == 1 and len(s.next) > 1 and not any(e.default for e in s.next):
                missing[0].default = True
                ctx.add("L10", "info", f"Единственный выход без подписи у шлюза {_q(s.name)} помечен как «иначе»",
                        [s.id], s.src, True)
            elif missing:
                ctx.add("L10", "warning", f"У шлюза {_q(s.name)} есть выходы без подписи условия", [s.id], s.src)


def l11_empty_participants(ctx: _Ctx) -> None:
    used = {s.participant for s in ctx.ir.steps}
    for p in list(ctx.ir.participants):
        if p.id not in used and len(ctx.ir.participants) > 1:
            ctx.ir.participants.remove(p)
            ctx.add("L11", "info", f"Участник «{p.name}» не выполняет шагов — дорожка удалена", [], [], True)





def lint(ir: ProcessIR) -> tuple[ProcessIR, list[Issue]]:
    """Вернуть (исправленный IR, замечания). Исходный объект не меняется."""
    ctx = _Ctx(copy.deepcopy(ir))
    if not ctx.ir.steps:
        ctx.add("L01", "error", "Не удалось извлечь ни одного шага процесса")
        return ctx.ir, ctx.issues
    for rule in RULES:
        rule(ctx)
    return ctx.ir, ctx.issues

def l12_dangling_parallel_branches(ctx: _Ctx) -> None:
    """После and-разветвления часть веток может не доходить до общей точки,
    если LLM не смоделировал and-слияние явно: одна ветка продолжает процесс
    дальше, а остальные сразу гаснут отдельными end-событиями (добавленными L06).
    Если ветка гаснет СРАЗУ после разветвления — она «пропущенная», её нужно
    подключить слиянием туда, куда ведёт ветка, которая продолжается дальше."""
    sm = ctx.ir.step_map()
    for gw in [s for s in ctx.ir.steps if s.type == "and" and len(s.next) > 1]:
        dead: list[tuple[Step, Step]] = []
        alive: list[Step] = []
        for e in gw.next:
            head = sm.get(e.to)
            if head is None or not head.next:
                continue
            tgt = sm.get(head.next[0].to)
            if len(head.next) == 1 and tgt is not None and tgt.type == "end" and tgt.origin == "autofix":
                dead.append((head, tgt))
            else:
                alive.append(head)
        if dead and len(alive) == 1:
            alive_head = alive[0]
            target = alive_head.next[0].to
            join = _insert_step(ctx, id=ctx.new_id("J"), type="and", name="",
                                participant=gw.participant, src=list(gw.src), next=[Edge(to=target)])
            alive_head.next = [Edge(to=join.id)]
            for head, end_node in dead:
                head.next = [Edge(to=join.id)]
                ctx.ir.steps.remove(end_node)
            name = sm[target].name if target in sm else target
            ctx.add("L12", "warning", f"После параллельного разветвления {_q(gw.name)} часть веток "
                    f"не была объединена перед «{name}» — добавлено параллельное слияние",
                    [gw.id, join.id], gw.src, True)

RULES = [l01_references, l02_self_loops, l03_trivial_gateways, l04_implicit_split, l05_start,
         l06_dead_ends, l12_dangling_parallel_branches, l07_implicit_merge, l09_orphan_branches, l08_unreachable,
         l10_unlabeled, l11_empty_participants]
