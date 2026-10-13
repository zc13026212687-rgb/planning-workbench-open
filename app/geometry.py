"""Original deterministic teaching road geometry, deliberately bounded in scope.

Geometry is computed in the declared drawing units. Curves remain true arcs in
the result and DXF; sampling is used only for topology, area and constraint QA.
Supported junctions are coplanar T/X junctions between straight
segments. Unsupported cases are reported, never silently replaced by a buffer.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

TAU = math.tau
EPS = 1e-7
# Validated algorithm envelope, not a road-design standard.
MIN_JUNCTION_ANGLE = math.radians(30)
UNIT_CODES = {"m": 6, "mm": 4, "cm": 5, "ft": 2, "in": 1}
CENTER_LAYERS = {"ROAD_CENTER", "CENTERLINE", "CENTER_LINE", "道路中心线", "中心线"}


def _add(a, b):
    return [a[0] + b[0], a[1] + b[1]]


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1]]


def _mul(a, n):
    return [a[0] * n, a[1] * n]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _length(a):
    return math.hypot(a[0], a[1])


def _left(a):
    return [-a[1], a[0]]


def _point(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(_number(v) and abs(v) <= 1e9 for v in value))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _sweep(s):
    raw = (s["start_angle"] - s["end_angle"]) if s.get("clockwise") else (s["end_angle"] - s["start_angle"])
    return raw % TAU


def _arcpoint(s, fraction=0.0, radius=None):
    angle = s["start_angle"] + (-1 if s.get("clockwise") else 1) * _sweep(s) * fraction
    r = s["radius"] if radius is None else radius
    return [s["center"][0] + r * math.cos(angle), s["center"][1] + r * math.sin(angle)]


def _endpoints(s):
    return (s["start"], s["end"]) if s["type"] == "line" else (_arcpoint(s), _arcpoint(s, 1))


def _sample_arc(entity, tolerance):
    sweep = (entity["end_angle"] - entity["start_angle"]) % TAU
    radius = entity["radius"]
    step = 2 * math.acos(max(-1, min(1, 1 - tolerance / radius))) if radius > tolerance else math.pi / 4
    count = max(2, math.ceil(sweep / max(step, 1e-8)))
    if count > 4096:
        raise ValueError("曲线范围过大或采样容差过小；每段弧最多支持 4096 个校核区间。")
    return [[entity["center"][0] + radius * math.cos(entity["start_angle"] + sweep * i / count),
             entity["center"][1] + radius * math.sin(entity["start_angle"] + sweep * i / count)] for i in range(count + 1)]


def generate(spec: dict) -> dict:
    """Generate renderable entities, explicit checks and editable source spec.

    errors/warnings/checks are lists of {code, message, ...} objects. An error
    prevents DXF export, although invalid constraint variants can be previewed.
    """
    original = copy.deepcopy(spec) if isinstance(spec, dict) else {}
    report = {"errors": [], "warnings": [], "checks": []}
    entities = []
    result = {"entities": entities, "bounds": [0, 0, 1, 1], "report": report,
              "metrics": {}, "spec": original}

    def issue(kind, code, message, **context):
        report[kind].append({"code": code, "message": message, **context})

    def error(code, message, **context):
        issue("errors", code, message, **context)

    if not isinstance(spec, dict):
        error("invalid_spec", "RoadSpec 必须是 JSON 对象。")
        return result
    units = spec.get("units")
    if units not in UNIT_CODES:
        error("units_required", "请确认图纸单位：m / mm / cm / ft / in；仅修改单位标签不会缩放坐标。")
    if not isinstance(spec.get("coordinate_reference"), str) or not spec.get("coordinate_reference", "").strip():
        error("coordinate_reference_required", "必须声明平面坐标基准，可使用 local_cartesian。")
    elif spec.get("coordinate_reference") != "local_cartesian":
        error("unsupported_crs", "当前几何引擎只接受明确的 local_cartesian 工程平面坐标。经纬度或 EPSG 图纸须先以已核实方法转换，不能直接按长度单位计算。")
    tolerance = spec.get("qa_tolerance", 0.01)
    if not _number(tolerance) or tolerance <= 0:
        error("invalid_tolerance", "qa_tolerance 必须是正的有限数。")
        tolerance = 0.01
    junction_radius = spec.get("junction_radius", 4)
    if not _number(junction_radius) or junction_radius < 0 or junction_radius > 1e9:
        error("invalid_junction_radius", "路口圆角半径必须是 0–1e9 范围内的有限数。")
        junction_radius = 0
    roads = spec.get("roads")
    if not isinstance(roads, list) or not roads or len(roads) > 200:
        error("invalid_roads", "需要 1–200 条道路。")
        return result
    if sum(len(r.get("segments", [])) if isinstance(r, dict) and isinstance(r.get("segments"), list) else 0 for r in roads) > 1000:
        error("too_many_segments", "教学版本最多支持 1000 个中心线段。")
        return result

    lines, arcs = [], []
    ids = set()
    total_length = 0.0
    for index, road in enumerate(roads):
        if not isinstance(road, dict):
            error("invalid_road", "每条道路必须是对象。", road_index=index)
            continue
        rid = road.get("id")
        if not isinstance(rid, str) or not rid.strip() or rid in ids:
            error("invalid_road_id", "道路 ID 必须非空且唯一。", road_index=index)
            continue
        ids.add(rid)
        lw, rw = road.get("left_width", spec.get("left_width")), road.get("right_width", spec.get("right_width"))
        if not _number(lw) or not _number(rw) or min(lw, rw) <= 0 or max(lw, rw) > 1e9:
            error("invalid_width", "左右宽度必须分别填写 0–1e9 范围内的正有限数。", road_id=rid)
            continue
        level = road.get("level", 0)
        if not _number(level) or int(level) != level:
            error("invalid_level", "level 必须是整数；不同标高道路不自动形成平交口。", road_id=rid)
            continue
        segments = road.get("segments")
        if not isinstance(segments, list) or not segments:
            error("segments_required", "道路需要至少一个中心线段。", road_id=rid)
            continue
        if len(segments) > 1 and any(isinstance(s, dict) and s.get("type") == "arc" for s in segments):
            error("unsupported_mixed_alignment", "首版只支持独立真圆弧或连续直线道路；直线—圆弧复合线形须拆分并单独校核连接。", road_id=rid)
            continue
        previous = None
        for si, segment in enumerate(segments):
            context = {"road_id": rid, "segment_index": si}
            if not isinstance(segment, dict) or segment.get("type") not in ("line", "arc"):
                error("unsupported_segment", "仅支持 line 或 arc 中心线。", **context)
                continue
            s = copy.deepcopy(segment)
            s.update(road_id=rid, name=road.get("name", rid), lw=float(lw), rw=float(rw), level=int(level), segment_index=si,
                     junction_type=road.get("junction_type", "at_grade"))
            if s["type"] == "line":
                if not _point(s.get("start")) or not _point(s.get("end")):
                    error("invalid_point", "直线端点必须是两个有限坐标。", **context)
                    continue
                length = _length(_sub(s["end"], s["start"]))
                if length <= EPS:
                    error("zero_length", "不能使用零长中心线。", **context)
                    continue
                s.update(length=length, u=_mul(_sub(s["end"], s["start"]), 1 / length), splits=[0.0, 1.0])
                lines.append(s)
            else:
                if (not _point(s.get("center")) or not _number(s.get("radius")) or not 0 < s["radius"] <= 1e9
                        or not _number(s.get("start_angle")) or not _number(s.get("end_angle"))):
                    error("invalid_arc", "圆弧需要有限圆心、正半径和以弧度表示的起止角。", **context)
                    continue
                if abs(s["end_angle"] - s["start_angle"]) >= TAU - EPS or _sweep(s) <= EPS:
                    error("unsupported_full_circle", "道路圆弧角度跨度需大于 0 且小于整圆。", **context)
                    continue
                inner_width = rw if s.get("clockwise") else lw
                if s["radius"] - inner_width <= EPS:
                    error("inner_radius_nonpositive", "内侧偏移半径必须大于 0；道路宽度不能达到或超过中心线半径。", **context)
                    continue
                s["length"] = s["radius"] * _sweep(s)
                arcs.append(s)
            start, end = _endpoints(s)
            if previous is not None and _length(_sub(previous, start)) > EPS:
                error("disconnected_alignment", "同一道路的相邻段不连续。", **context)
            previous = end
            total_length += s["length"]
    if report["errors"]:
        return result

    # Analytic line intersections split centerlines into graph edges.
    for i, a in enumerate(lines):
        for b in lines[i + 1:]:
            if a["level"] != b["level"]:
                continue
            av, bv = _sub(a["end"], a["start"]), _sub(b["end"], b["start"])
            delta = _sub(b["start"], a["start"])
            denom = _cross(av, bv)
            if abs(denom) <= EPS * a["length"] * b["length"]:
                if abs(_cross(delta, a["u"])) <= EPS:
                    values = sorted([_dot(_sub(p, a["start"]), a["u"]) for p in (b["start"], b["end"])])
                    if min(a["length"], values[1]) - max(0, values[0]) > EPS:
                        error("overlapping_centerlines", "同标高中心线存在共线重叠，请去重。", road_id=a["road_id"], other_road_id=b["road_id"])
                continue
            t, v = _cross(delta, bv) / denom, _cross(delta, av) / denom
            if -EPS <= t <= 1 + EPS and -EPS <= v <= 1 + EPS:
                if a["road_id"] != b["road_id"] and any(s.get("junction_type") != "at_grade" for s in (a, b)):
                    error("needs_confirmation", "相交道路的交叉形式尚未确认；请明确 at_grade 或经核实的独立 level，不能默认平交。", road_id=a["road_id"], other_road_id=b["road_id"])
                else:
                    a["splits"].append(max(0, min(1, t)))
                    b["splits"].append(max(0, min(1, v)))

    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize_full, unary_union

    # Arc intersections are deliberately rejected rather than mis-trimmed.
    center_curves = []
    for s in lines + arcs:
        if s["type"] == "line":
            points = [s["start"], s["end"]]
        else:
            canonical = dict(s)
            if s.get("clockwise"):
                canonical["start_angle"], canonical["end_angle"] = s["end_angle"], s["start_angle"]
            try:
                points = _sample_arc(canonical, tolerance)
            except ValueError as exc:
                error("sampling_limit", str(exc), road_id=s["road_id"])
                continue
        center_curves.append((s, LineString(points)))
    for i, (a, ga) in enumerate(center_curves):
        for b, gb in center_curves[i + 1:]:
            if a["level"] == b["level"] and (a["type"] == "arc" or b["type"] == "arc") and ga.distance(gb) <= tolerance:
                error("unsupported_arc_junction", "圆弧中心线接近或相交于另一条中心线；首版不自动求该路口。", road_id=a["road_id"], other_road_id=b["road_id"])
    # Catch merging road envelopes whose centerlines do not form a supported
    # junction (near misses, parallel overlaps, and overlapping arc envelopes).
    corridors = []
    for s, centerline in center_curves:
        if s["type"] == "line":
            n = _left(s["u"])
            ring = [_add(s["start"], _mul(n, s["lw"])), _add(s["end"], _mul(n, s["lw"])),
                    _add(s["end"], _mul(n, -s["rw"])), _add(s["start"], _mul(n, -s["rw"]))]
        else:
            canonical = dict(s)
            if s.get("clockwise"):
                canonical["start_angle"], canonical["end_angle"] = s["end_angle"], s["start_angle"]
            lr = s["radius"] + s["lw"] if s.get("clockwise") else s["radius"] - s["lw"]
            rr = s["radius"] - s["rw"] if s.get("clockwise") else s["radius"] + s["rw"]
            try:
                ring = _sample_arc({**canonical, "radius": lr}, tolerance) + list(reversed(_sample_arc({**canonical, "radius": rr}, tolerance)))
            except ValueError as exc:
                error("sampling_limit", str(exc), road_id=s["road_id"])
                continue
        corridors.append((s, centerline, Polygon(ring)))
    for i, (a, ga, pa) in enumerate(corridors):
        for b, gb, pb in corridors[i + 1:]:
            if a["level"] == b["level"] and ga.distance(gb) > tolerance and pa.intersection(pb).area > max(EPS, tolerance * tolerance):
                error("unconnected_corridor_overlap", "道路面重叠但中心线未形成已支持的连接节点，请修正中心线或标高关系。", road_id=a["road_id"], other_road_id=b["road_id"])
    if report["errors"]:
        return result

    def emit(kind, layer, **values):
        entity = {"id": f"e{len(entities) + 1:05d}", "type": kind, "layer": layer, **values}
        entities.append(entity)
        return entity

    def emit_arc(s, radius, layer):
        start, end = s["start_angle"], s["end_angle"]
        if s.get("clockwise"):
            start, end = end, start
        return emit("arc", layer, center=list(s["center"]), radius=radius, start_angle=start,
                    end_angle=end, road_id=s["road_id"], level=s["level"])

    nodes, pieces = {}, []
    def node_key(p, level):
        return (round(p[0], 7), round(p[1], 7), level)

    for s in lines:
        emit("line", "ROAD_CENTER", start=s["start"], end=s["end"], road_id=s["road_id"], level=s["level"])
        splits = sorted(set(round(t, 12) for t in s["splits"]))
        for t0, t1 in zip(splits, splits[1:]):
            if (t1 - t0) * s["length"] <= EPS:
                continue
            p0 = _add(s["start"], _mul(s["u"], t0 * s["length"]))
            p1 = _add(s["start"], _mul(s["u"], t1 * s["length"]))
            piece = {**s, "start": p0, "end": p1, "length": (t1 - t0) * s["length"], "trims": [[0.0, 0.0], [0.0, 0.0]]}
            pi = len(pieces)
            pieces.append(piece)
            for end_index, point in enumerate((p0, p1)):
                u = s["u"] if end_index == 0 else _mul(s["u"], -1)
                ray = {"piece": pi, "end": end_index, "u": u, "angle": math.atan2(u[1], u[0]) % TAU,
                       "left": s["lw"] if end_index == 0 else s["rw"],
                       "right": s["rw"] if end_index == 0 else s["lw"]}
                key = node_key(point, s["level"])
                nodes.setdefault(key, {"point": point, "level": s["level"], "rays": []})["rays"].append(ray)

    junctions = 0
    for node in nodes.values():
        rays = sorted(node["rays"], key=lambda r: r["angle"])
        count, p = len(rays), node["point"]
        if count == 1:
            r = rays[0]
            n = _left(r["u"])
            emit("line", "ROAD_CAP", start=_add(p, _mul(n, r["left"])), end=_add(p, _mul(n, -r["right"])), level=node["level"], road_id=pieces[r["piece"]]["road_id"])
            continue
        gaps = [(rays[(i + 1) % count]["angle"] - rays[i]["angle"]) % TAU for i in range(count)]
        opposite_pairs = sum(1 for i, a in enumerate(rays) for b in rays[i + 1:]
                             if abs(_cross(a['u'], b['u'])) <= 1e-6 and _dot(a['u'], b['u']) < 0)
        if (count not in (2, 3, 4) or opposite_pairs != (2 if count == 4 else 1)
                or any(g > math.pi + 1e-6 for g in gaps)):
            error("unsupported_node", "仅支持直线连续节点、带直行主路的 T 口及两条直路 X 口；Y 口、多岔和折线弯折暂不支持。", position=p)
            continue
        if count >= 3 and any(g < MIN_JUNCTION_ANGLE - 1e-8 for g in gaps):
            error("junction_angle_out_of_range", "当前算法验证范围为两条直路较小夹角 30–90 度（算法边界，不是规范限值）。", position=p,
                  minimum_angle_degrees=round(math.degrees(min(gaps)), 8))
            continue
        if count >= 3:
            junctions += 1
        for i, a in enumerate(rays):
            b = rays[(i + 1) % count]
            theta = gaps[i]
            if abs(theta - math.pi) <= 1e-6:
                if abs(a["left"] - b["right"]) > EPS:
                    error("unsupported_width_transition", "直线连续方向的两侧宽度不同；首版尚不支持突变宽度。", position=p)
                continue
            # Intersection of the two inside offset lines, then a true circle
            # tangent to each. d = R cot(theta/2); at 90 degrees d = R.
            pa = _add(p, _mul(_left(a["u"]), a["left"]))
            pb = _add(p, _mul(_left(b["u"]), -b["right"]))
            distance = _cross(_sub(pb, pa), b["u"]) / _cross(a["u"], b["u"])
            corner = _add(pa, _mul(a["u"], distance))
            tangent_length = junction_radius / math.tan(theta / 2)
            ta, tb = _add(corner, _mul(a["u"], tangent_length)), _add(corner, _mul(b["u"], tangent_length))
            trim_a, trim_b = _dot(_sub(ta, p), a["u"]), _dot(_sub(tb, p), b["u"])
            if min(trim_a, trim_b) < -EPS:
                error("unsupported_offset_reversal", "夹角与宽度组合使相切点越过中心线节点；当前不延伸反向边线，请调整线形、宽度或圆角并重新校核。",
                      position=p, corner_angle_degrees=round(math.degrees(theta), 8), trims=[trim_a, trim_b])
                continue
            pieces[a["piece"]]["trims"][a["end"]][0] = max(0, trim_a)
            pieces[b["piece"]]["trims"][b["end"]][1] = max(0, trim_b)
            if junction_radius > EPS:
                bisector = _add(a["u"], b["u"])
                center = _add(corner, _mul(bisector, junction_radius / (math.sin(theta / 2) * _length(bisector))))
                emit("arc", "ROAD_JUNCTION", center=center, radius=float(junction_radius),
                     start_angle=math.atan2(tb[1] - center[1], tb[0] - center[0]),
                     end_angle=math.atan2(ta[1] - center[1], ta[0] - center[0]), level=node["level"])
        if count >= 3:
            issue("checks", "junction_angles", "按已确认平交关系求解偏移交点与相切圆角；夹角为几何量。", position=p,
                  junction_kind="T" if count == 3 else "X", sector_angles_degrees=[round(math.degrees(g), 8) for g in gaps],
                  radius=junction_radius, algorithm_minimum_angle_degrees=30)

    for p in pieces:
        n = _left(p["u"])
        for side, width in enumerate((p["lw"], -p["rw"])):
            trim_start = p["trims"][0][side]
            trim_end = p["trims"][1][1 - side]
            if trim_start + trim_end >= p["length"] - EPS:
                error("insufficient_junction_space", "中心线段不足以容纳路宽及两端路口圆角；请减小半径或调整中心线。", road_id=p["road_id"])
                continue
            emit("line", "ROAD_EDGE", start=_add(_add(p["start"], _mul(n, width)), _mul(p["u"], trim_start)),
                 end=_add(_add(p["end"], _mul(n, width)), _mul(p["u"], -trim_end)), road_id=p["road_id"], level=p["level"])

    for s in arcs:
        emit_arc(s, s["radius"], "ROAD_CENTER")
        lr = s["radius"] + s["lw"] if s.get("clockwise") else s["radius"] - s["lw"]
        rr = s["radius"] - s["rw"] if s.get("clockwise") else s["radius"] + s["rw"]
        emit_arc(s, lr, "ROAD_EDGE")
        emit_arc(s, rr, "ROAD_EDGE")
        for t in (0, 1):
            emit("line", "ROAD_CAP", start=_arcpoint(s, t, lr), end=_arcpoint(s, t, rr), road_id=s["road_id"], level=s["level"])
    if report["errors"]:
        entities.clear()  # Incomplete boundary geometry must not look exportable.
        return result

    # Polygonize the actual offset edges / fillets, rather than buffering a
    # centerline. Precision rounding joins independently computed tangent ends.
    boundaries = {}
    for e in entities:
        if e["layer"] not in ("ROAD_EDGE", "ROAD_JUNCTION", "ROAD_CAP"):
            continue
        try:
            points = [e["start"], e["end"]] if e["type"] == "line" else _sample_arc(e, tolerance)
        except ValueError as exc:
            error("sampling_limit", str(exc))
            continue
        points = [(round(x, 7), round(y, 7)) for x, y in points]
        boundaries.setdefault(e.get("level", 0), []).append(LineString(points))
    footprints = {}
    for level, linestrings in boundaries.items():
        polygon_collection, cuts, dangles, invalid_rings = polygonize_full(unary_union(linestrings))
        polygons = list(polygon_collection.geoms)
        if not cuts.is_empty or not dangles.is_empty or not invalid_rings.is_empty:
            error("incomplete_boundary", "边界存在悬线、切线或无效环，禁止将局部闭合结果当作完整道路。", level=level)
        if not polygons:
            error("boundary_not_closed", "生成边界未形成闭合道路面，禁止导出。", level=level)
        else:
            footprint = unary_union(polygons)
            footprints[level] = footprint
            if not footprint.is_valid:
                error("invalid_road_polygon", "生成道路面拓扑无效。", level=level)
    footprint_all = unary_union(list(footprints.values()))

    constraints = spec.get("constraints", [])
    if not isinstance(constraints, list):
        error("invalid_constraints", "constraints 必须是数组。")
        constraints = []
    for ci, c in enumerate(constraints):
        if not isinstance(c, dict) or c.get("type") not in ("preserve", "no_build"):
            error("unsupported_constraint", "仅支持 preserve 与 no_build 多边形约束。", constraint_index=ci)
            continue
        pts = c.get("polygon")
        if not isinstance(pts, list) or len(pts) < 3 or not all(_point(p) for p in pts):
            error("invalid_constraint_polygon", "约束需要至少 3 个有效坐标。", constraint_id=c.get("id", str(ci)))
            continue
        polygon = Polygon(pts)
        if not polygon.is_valid or polygon.area <= EPS:
            error("invalid_constraint_polygon", "约束多边形自交或面积为零。", constraint_id=c.get("id", str(ci)))
            continue
        cid = c.get("id", f"constraint-{ci}")
        emit("polyline", "RETAINED_OBJECT" if c.get("status") == "retained" else "CONSTRAINT", points=pts, closed=True, constraint_id=cid)
        area = footprint_all.intersection(polygon).area
        if footprint_all.distance(polygon) <= tolerance:
            error("constraint_conflict", "道路边界接触或侵入保留/禁建约束，请调整方案。", constraint_id=cid,
                  overlap_area=round(area, 6), tolerance=tolerance)
        else:
            issue("checks", "constraint_clear", "道路避让约束通过。", constraint_id=cid,
                  clearance=round(footprint_all.distance(polygon), 6))

    for s in roads:
        first = s["segments"][0]
        position = _endpoints(first)[0]
        emit("text", "ROAD_LABEL", position=list(position), text=str(s.get("name", s["id"])),
             height=max(0.2, min(s.get("left_width", spec.get("left_width")), s.get("right_width", spec.get("right_width"))) * 0.22))
    context = spec.get("context_entities", [])
    if isinstance(context, list):
        for e in context[:1000]:
            if _valid_entity(e):
                e = copy.deepcopy(e)
                e["id"] = f"e{len(entities) + 1:05d}"
                safe_context_layers = {"CONTEXT", "EXISTING_ROAD", "BLOCK_BOUNDARY", "RETAINED_OBJECT"}
                e["layer"] = e.get("layer") if e.get("layer") in safe_context_layers else "CONTEXT"
                entities.append(e)
            else:
                issue("warnings", "invalid_context_skipped", "无效背景图元已跳过。")
    else:
        error("invalid_context", "context_entities 必须是数组。")
    issue("checks", "analytic_offsets", "直线法向偏移与圆弧同心偏移采用解析计算。")
    issue("checks", "junction_geometry", f"已生成 {junctions} 个 T/X 路口；转角使用真实相切圆弧，夹角见逐口记录。")
    if not any(e["code"] in ("boundary_not_closed", "invalid_road_polygon", "incomplete_boundary", "sampling_limit") for e in report["errors"]):
        issue("checks", "closed_boundaries", "按实际边线及圆角离散校核道路面闭合。", qa_tolerance=tolerance)
    if any(r.get("level", 0) != 0 for r in roads):
        issue("warnings", "logical_levels_only", "level 仅决定平交连通性，不是实际高程；当前输出为二维平面，不生成桥梁或纵断面。")
    issue("warnings", "planning_scope", "结果用于教学与规划方案研究，未自动套用道路工程规范，不构成施工设计。")
    issue("warnings", "sampled_qa", "圆弧输出保持精确；面积与碰撞采用声明容差的离散校核，临界边界仍需工程复核。", qa_tolerance=tolerance)
    # Status is presentation metadata applied AFTER geometric QA; centreline
    # layer stays stable for editable DXF round trips. No status implies legacy layers.
    statuses = {r["id"]: r.get("status") for r in roads}
    for entity in entities:
        status = statuses.get(entity.get("road_id"))
        if status in ("retained", "proposed"):
            entity["status"] = status
            if entity["layer"] in ("ROAD_EDGE", "ROAD_CAP"):
                entity["layer"] = f"{status.upper()}_{entity['layer']}"
    result["metrics"] = {"road_count": len(roads), "line_segment_count": len(lines), "arc_segment_count": len(arcs),
                         "junction_count": junctions, "total_centerline_length": round(total_length, 6),
                         "road_area": round(sum(p.area for p in footprints.values()), 6),
                         "length_unit": units, "area_unit": f"{units}²", "qa_tolerance": tolerance,
                         "entity_count": len(entities)}
    result["bounds"] = _bounds(entities)
    return result


def _valid_entity(e):
    if not isinstance(e, dict):
        return False
    kind = e.get("type")
    if kind == "line":
        return _point(e.get("start")) and _point(e.get("end"))
    if kind == "arc":
        return (_point(e.get("center")) and _number(e.get("radius")) and e["radius"] > 0
                and _number(e.get("start_angle")) and _number(e.get("end_angle")))
    if kind == "polyline":
        return isinstance(e.get("points"), list) and len(e["points"]) >= 2 and all(_point(p) for p in e["points"])
    if kind == "text":
        return _point(e.get("position")) and isinstance(e.get("text"), str) and _number(e.get("height")) and e["height"] > 0
    return False


def _bounds(entities):
    points = []
    for e in entities:
        if e["type"] == "line":
            points += [e["start"], e["end"]]
        elif e["type"] == "polyline":
            points += e["points"]
        elif e["type"] == "text":
            points += [e["position"]]
        elif e["type"] == "arc":
            a, b = e["start_angle"], e["end_angle"]
            angles = [a, b] + [k * math.pi / 2 for k in range(4) if (k * math.pi / 2 - a) % TAU <= (b - a) % TAU + EPS]
            points += [[e["center"][0] + e["radius"] * math.cos(t), e["center"][1] + e["radius"] * math.sin(t)] for t in angles]
    if not points:
        return [0, 0, 1, 1]
    return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]


def export_dxf(result: dict, path: Path):
    """Write new DXF with true ARC/bulge curves and editable centerline metadata."""
    if result.get("report", {}).get("errors"):
        raise ValueError("图纸仍有校核错误，不能作为合格成果导出。")
    spec = result["spec"]
    if spec.get("units") not in UNIT_CODES:
        raise ValueError("导出前必须确认图纸单位。")
    import ezdxf
    doc = ezdxf.new("R2013")
    doc.units = UNIT_CODES[spec["units"]]
    doc.header["$MEASUREMENT"] = 1 if spec["units"] in ("m", "mm", "cm") else 0
    doc.appids.add("PLANNINGWB")
    colors = {"ROAD_CENTER": 1, "ROAD_EDGE": 7, "ROAD_JUNCTION": 3, "ROAD_CAP": 7,
              "CONSTRAINT": 2, "CONTEXT": 8, "ROAD_LABEL": 5, "RETAINED_OBJECT": 2,
              "BLOCK_BOUNDARY": 9, "EXISTING_ROAD": 8, "RETAINED_ROAD_EDGE": 8,
              "PROPOSED_ROAD_EDGE": 4, "RETAINED_ROAD_CAP": 8, "PROPOSED_ROAD_CAP": 4}
    for layer, color in colors.items():
        doc.layers.new(layer, dxfattribs={"color": color})
    msp = doc.modelspace()
    # One editable LWPOLYLINE per road; exact signed bulges preserve arcs.
    for road in spec["roads"]:
        vertices = []
        for s in road["segments"]:
            start, end = _endpoints(s)
            bulge = 0 if s["type"] == "line" else math.tan(_sweep(s) * (-1 if s.get("clockwise") else 1) / 4)
            vertices.append((start[0], start[1], bulge))
        vertices.append((end[0], end[1], 0))
        entity = msp.add_lwpolyline(vertices, format="xyb", dxfattribs={"layer": "ROAD_CENTER"})
        entity.set_xdata("PLANNINGWB", [(1000, road["id"])])
    for e in result["entities"]:
        if e["layer"] == "ROAD_CENTER":
            continue
        layer = e["layer"]
        if layer not in doc.layers:
            doc.layers.new(layer)
        attrs = {"layer": layer}
        if e["type"] == "line":
            msp.add_line(e["start"], e["end"], dxfattribs=attrs)
        elif e["type"] == "arc":
            msp.add_arc(e["center"], e["radius"], math.degrees(e["start_angle"]) % 360,
                        math.degrees(e["end_angle"]) % 360, dxfattribs=attrs)
        elif e["type"] == "polyline":
            msp.add_lwpolyline(e["points"], close=e.get("closed", False), dxfattribs=attrs)
        elif e["type"] == "text":
            msp.add_text(e["text"], dxfattribs={**attrs, "height": e["height"], "insert": e["position"]})
    payload = json.dumps(spec, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    record = doc.rootdict.add_xrecord("PLANNINGWB_ROADSPEC")
    record.reset([(1, payload[i:i + 200]) for i in range(0, len(payload), 200)])
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"目标文件已存在，请使用新文件名：{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)


def _bulge_segment(p, q, bulge):
    p, q, bulge = [float(v) for v in p], [float(v) for v in q], float(bulge)
    if abs(bulge) <= EPS:
        return {"type": "line", "start": list(p), "end": list(q)}
    chord = _sub(q, p)
    length = _length(chord)
    if length <= EPS:
        raise ValueError("多段线圆弧具有重合端点，不能确定线形。")
    center = _add(_mul(_add(p, q), 0.5), _mul(_left(chord), (1 - bulge * bulge) / (4 * bulge)))
    return {"type": "arc", "center": center, "radius": length * (1 + bulge * bulge) / (4 * abs(bulge)),
            "start_angle": math.atan2(p[1] - center[1], p[0] - center[0]),
            "end_angle": math.atan2(q[1] - center[1], q[0] - center[0]), "clockwise": bulge < 0}


def _dxf_segments(entity):
    kind = entity.dxftype()
    if kind == "LINE":
        if abs(entity.dxf.start.z) > EPS or abs(entity.dxf.end.z) > EPS:
            raise ValueError("暂不导入带高程的 LINE，请明确转换为世界 XY 平面；系统不会静默丢弃高程。")
        return [{"type": "line", "start": list(entity.dxf.start)[:2], "end": list(entity.dxf.end)[:2]}]
    if kind == "ARC":
        if abs(entity.dxf.center.z) > EPS or tuple(entity.dxf.extrusion) != (0.0, 0.0, 1.0):
            raise ValueError("暂不导入带高程或倾斜 OCS 的 ARC，请转换为世界 XY 平面。")
        return [{"type": "arc", "center": list(entity.dxf.center)[:2], "radius": entity.dxf.radius,
                 "start_angle": math.radians(entity.dxf.start_angle), "end_angle": math.radians(entity.dxf.end_angle)}]
    if kind == "LWPOLYLINE":
        if tuple(entity.dxf.extrusion) != (0.0, 0.0, 1.0) or abs(entity.dxf.elevation) > EPS:
            raise ValueError("暂不支持倾斜 OCS 多段线，请在 CAD 中转换为世界 XY 平面。")
        points = list(entity.get_points("xyb"))
        count = len(points) if entity.closed else len(points) - 1
        return [_bulge_segment(points[i][:2], points[(i + 1) % len(points)][:2], points[i][2]) for i in range(count)]
    return []


def import_dxf(path: Path) -> dict:
    """Read source centerlines. Never assume metres or widths for external DXF.

    Our own metadata supplies design parameters, but actual DXF centerlines are
    always reread, so a CAD edit cannot be silently ignored in favour of a stale
    embedded spec. DXF LINE/ARC and LWPOLYLINE bulges remain analytic segments.
    """
    import ezdxf
    path = Path(path)
    if path.suffix.lower() != ".dxf":
        raise ValueError("当前仅支持 DXF，DWG 需通过合法 CAD 工具转换。")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("教学版 DXF 文件上限为 20 MB。")
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    warnings = []
    meta = {}
    try:
        record = doc.rootdict.get("PLANNINGWB_ROADSPEC")
        if record:
            raw = "".join(str(tag.value) for tag in record.tags if tag.code == 1)
            if len(raw) <= 2_000_000:
                value = json.loads(raw)
                if isinstance(value, dict):
                    meta = value
    except (ValueError, TypeError, AttributeError):
        warnings.append("内嵌道路参数无法读取，将使用实际中心线并要求重新确认参数。")
    candidates = [e for e in msp if e.dxftype() in ("LINE", "ARC", "LWPOLYLINE") and e.dxf.layer.upper() in CENTER_LAYERS]
    if not candidates:
        candidates = [e for e in msp if e.dxftype() in ("LINE", "ARC", "LWPOLYLINE")]
        warnings.append("未识别专用中心线图层，已将 LINE/ARC/LWPOLYLINE 作为候选中心线；请确认并删除非道路对象。")
    if len(candidates) > 200:
        raise ValueError("候选中心线超过 200 个，请在 CAD 中隔离道路中心线图层后重试。")
    if not candidates:
        raise ValueError("DXF 中未发现可导入的道路中心线。")
    old_roads = {r.get("id"): r for r in meta.get("roads", []) if isinstance(r, dict)}
    roads, seen = [], set()
    for i, entity in enumerate(candidates):
        rid = None
        try:
            rid = next((str(tag.value) for tag in entity.get_xdata("PLANNINGWB") if tag.code == 1000), None)
        except ezdxf.DXFValueError:
            pass
        if not rid or rid in seen:
            rid = f"import-{i + 1}"
        seen.add(rid)
        road = copy.deepcopy(old_roads.get(rid, {}))
        road.update(id=rid, name=road.get("name", f"导入中心线 {i + 1}"), segments=_dxf_segments(entity))
        road.setdefault("level", 0)
        roads.append(road)
    units = next((u for u, code in UNIT_CODES.items() if code == doc.units), None)
    if units is None:
        warnings.append("DXF 未声明支持的单位，必须人工确认 units；坐标尚未缩放。")
    if meta.get("units") and meta["units"] != units:
        warnings.append("DXF 单位标签与内嵌参数不同，采用 DXF 标签但未缩放坐标；请核实。")
    spec = copy.deepcopy(meta)
    spec.update(units=units, coordinate_reference=meta.get("coordinate_reference", "local_cartesian"),
                left_width=meta.get("left_width"), right_width=meta.get("right_width"),
                junction_radius=meta.get("junction_radius", 0), roads=roads,
                constraints=meta.get("constraints", []), context_entities=meta.get("context_entities", []))
    if not meta:
        warnings.append("外部 DXF 不包含道路宽度、规划约束与坐标系信息，需确认这些参数后生成。")
    spec["_import"] = {"filename": path.name, "warnings": warnings,
                       "source_layers": sorted({e.dxf.layer for e in candidates}), "actual_geometry_reread": True}
    return spec
