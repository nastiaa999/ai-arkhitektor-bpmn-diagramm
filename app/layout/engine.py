"""M6: раскладка «дорожка × ранг» + ортогональные стрелки. Вход: ProcessIR как dict."""
import sys
from collections import defaultdict, deque

sys.setrecursionlimit(5000)

GATEWAYS = {"xor", "and", "or"}
EVENTS = {"start", "end", "timer", "message_catch"}
COL, ROW, HEAD, PAD = 160, 120, 30, 40
POOL_X, POOL_Y = 160, 60
OFFS = [0, 8, -8, 16, -16, 24, -24]


def size(t):
    if t in GATEWAYS:
        return 50, 50
    if t in EVENTS:
        return 36, 36
    return 100, 80


def ir_edges(ir):
    ids = {s["id"] for s in ir["steps"]}
    edges = []
    for s in ir["steps"]:
        for n in s.get("next") or []:
            if n["to"] in ids and n["to"] != s["id"]:
                edges.append({"i": len(edges), "src": s["id"], "dst": n["to"],
                              "label": n.get("label") or "", "default": bool(n.get("default"))})
    return edges


def _crossings(edge_pts):
    segs = [(k, a, b) for k, pts in enumerate(edge_pts) for a, b in zip(pts, pts[1:])]
    n = 0
    for x in range(len(segs)):
        for y in range(x + 1, len(segs)):
            k1, a1, b1 = segs[x]
            k2, a2, b2 = segs[y]
            if k1 == k2:
                continue
            h1, h2 = a1[1] == b1[1], a2[1] == b2[1]
            if h1 == h2:
                continue
            (ha, hb), (va, vb) = ((a1, b1), (a2, b2)) if h1 else ((a2, b2), (a1, b1))
            if min(ha[0], hb[0]) < va[0] < max(ha[0], hb[0]) and min(va[1], vb[1]) < ha[1] < max(va[1], vb[1]):
                n += 1
    return n


def compute_layout(ir):
    steps = {s["id"]: s for s in ir.get("steps", [])}
    order = list(steps)
    if not order:
        raise ValueError("Пустой процесс")
    parts = {p["id"]: p["name"] for p in ir.get("participants", [])} or \
        {"_p": (ir.get("process") or {}).get("name") or "Процесс"}
    first = next(iter(parts))
    lane_of = {i: (s.get("participant") if s.get("participant") in parts else first) for i, s in steps.items()}

    edges = ir_edges(ir)
    out, inc = defaultdict(list), defaultdict(list)
    for e in edges:
        out[e["src"]].append(e)
        inc[e["dst"]].append(e)
    roots = [i for i in order if steps[i]["type"] == "start"] or [i for i in order if not inc[i]] or order[:1]

    # порядок дорожек: по первому появлению при обходе в ширину
    seen, vis, q = [], set(roots), deque(roots)
    while q:
        u = q.popleft()
        seen.append(u)
        for e in out[u]:
            if e["dst"] not in vis:
                vis.add(e["dst"])
                q.append(e["dst"])
    seen += [i for i in order if i not in vis]
    lane_order = []
    for i in seen:
        if lane_of[i] not in lane_order:
            lane_order.append(lane_of[i])
    lane_order += [p for p in parts if p not in lane_order]
    lane_idx = {l: k for k, l in enumerate(lane_order)}

    # разрыв циклов
    state, back = {}, set()

    def dfs(u):
        state[u] = 1
        for e in out[u]:
            v = e["dst"]
            if state.get(v) == 1:
                back.add(e["i"])
            elif v not in state:
                dfs(v)
        state[u] = 2

    for r in roots + order:
        if r not in state:
            dfs(r)

    # ранги (длиннейший путь)
    fwd = [e for e in edges if e["i"] not in back]
    indeg, fo, fin = defaultdict(int), defaultdict(list), defaultdict(list)
    for e in fwd:
        indeg[e["dst"]] += 1
        fo[e["src"]].append(e["dst"])
        fin[e["dst"]].append(e["src"])
    rank = {i: 0 for i in order}
    q = deque(i for i in order if indeg[i] == 0)
    while q:
        u = q.popleft()
        for v in fo[u]:
            rank[v] = max(rank[v], rank[u] + 1)
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)

    # главный путь («хребет»)
    main, v = set(), max(order, key=lambda i: (rank[i], steps[i]["type"] == "end"))
    while v:
        main.add(v)
        preds = [p for p in fin[v] if rank[p] == rank[v] - 1]
        v = preds[0] if preds else None

    # подстроки в ячейках
    cells = defaultdict(list)
    for i in order:
        cells[(lane_of[i], rank[i])].append(i)
    maxrank = max(rank.values())
    sub, lane_sub = {}, {}
    for r in range(maxrank + 1):
        for l in lane_order:
            ids = cells.get((l, r))
            if not ids:
                continue
            m = [i for i in ids if i in main]
            o = [i for i in ids if i not in main]

            def bary(i, l=l):
                ys = [lane_idx[lane_of[p]] * 100 + sub[p] for p in fin[i] if p in sub]
                return sum(ys) / len(ys) if ys else lane_idx[l] * 100

            o.sort(key=bary)
            for i in m:
                sub[i] = 0
            nxt = 1 if m else 0
            for i in o:
                sub[i] = nxt
                nxt += 1
            lane_sub[l] = max(lane_sub.get(l, 1), nxt)

    nb = defaultdict(int)
    for e in edges:
        if e["i"] in back:
            nb[lane_of[e["src"]]] += 1
    lane_h = {l: lane_sub.get(l, 1) * ROW + ((12 * nb[l] + 8) if nb[l] else 0) for l in lane_order}
    lane_top, y = {}, POOL_Y
    for l in lane_order:
        lane_top[l] = y
        y += lane_h[l]
    width = HEAD + PAD + (maxrank + 1) * COL + PAD
    pool = {"x": POOL_X, "y": POOL_Y, "w": width, "h": y - POOL_Y}
    lane_x = POOL_X + HEAD

    shapes = {}
    for i in order:
        w, h = size(steps[i]["type"])
        cx = lane_x + PAD + rank[i] * COL + COL // 2
        cy = lane_top[lane_of[i]] + sub[i] * ROW + 60
        shapes[i] = {"x": cx - w // 2, "y": cy - h // 2, "w": w, "h": h, "cx": cx, "cy": cy}

    # маршрутизация
    gap_used, chan, gw_dir = defaultdict(int), defaultdict(int), set()
    routed = []
    for e in edges:
        s, t = shapes[e["src"]], shapes[e["dst"]]
        sl = lane_of[e["src"]]
        if e["i"] in back:
            yc = lane_top[sl] + lane_h[sl] - 8 - 12 * chan[sl]
            chan[sl] += 1
            end = (t["cx"], t["y"]) if t["y"] > yc else (t["cx"], t["y"] + t["h"])
            pts = [(s["cx"], s["y"] + s["h"]), (s["cx"], yc), (t["cx"], yc), end]
        elif s["cy"] == t["cy"]:
            pts = [(s["x"] + s["w"], s["cy"]), (t["x"], t["cy"])]
        elif steps[e["src"]]["type"] in GATEWAYS and (e["src"], t["cy"] < s["cy"]) not in gw_dir:
            up = t["cy"] < s["cy"]
            gw_dir.add((e["src"], up))
            pts = [(s["cx"], s["y"] if up else s["y"] + s["h"]), (s["cx"], t["cy"]), (t["x"], t["cy"])]
        else:
            gx = t["x"] - 30
            mx = gx + OFFS[gap_used[gx] % len(OFFS)]
            gap_used[gx] += 1
            pts = [(s["x"] + s["w"], s["cy"]), (mx, s["cy"]), (mx, t["cy"]), (t["x"], t["cy"])]
        lb = None
        if e["label"]:
            (x0, y0), (x1, y1) = pts[0], pts[1]
            w = int(max(24, len(e["label"]) * 6.5 + 6))
            if y0 == y1:
                lb = {"x": x0 + 4, "y": y0 - 22, "w": w, "h": 18}
            else:
                lb = {"x": x0 + 4, "y": y0 - 20 if y1 < y0 else y0 + 4, "w": w, "h": 18}
        routed.append({**e, "points": [(int(round(a)), int(round(b))) for a, b in pts], "label_bounds": lb})

    ids = list(shapes)
    overlaps = sum(
        1 for a in range(len(ids)) for b in range(a + 1, len(ids))
        if shapes[ids[a]]["x"] < shapes[ids[b]]["x"] + shapes[ids[b]]["w"]
        and shapes[ids[b]]["x"] < shapes[ids[a]]["x"] + shapes[ids[a]]["w"]
        and shapes[ids[a]]["y"] < shapes[ids[b]]["y"] + shapes[ids[b]]["h"]
        and shapes[ids[b]]["y"] < shapes[ids[a]]["y"] + shapes[ids[a]]["h"])

    return {
        "shapes": shapes, "edges": routed, "pool": pool,
        "lane_order": lane_order, "lane_names": parts, "lane_of": lane_of,
        "lanes": {l: {"x": lane_x, "y": lane_top[l], "w": width - HEAD, "h": lane_h[l]} for l in lane_order},
        "metrics": {"lanes": len(lane_order), "overlaps": overlaps,
                    "crossings": _crossings([r["points"] for r in routed])},
    }
