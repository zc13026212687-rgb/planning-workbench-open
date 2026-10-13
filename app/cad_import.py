"""Pure, explicit import of an inspected AutoCAD Pickfirst centerline selection.

No COM, file I/O, document ownership changes, coordinate scaling or design
defaults occur here. The API caller must obtain a fresh inspect_active snapshot
and an explicit user confirmation of the selection's centerline meaning.
"""
from __future__ import annotations

import hashlib
import json
import math
import re


class CadImportError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise CadImportError(code, message)


def _number(value, label, *, bound=1e9):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or abs(value) > bound):
        _fail("invalid_geometry", f"{label} 必须是范围内的有限数。")
    return float(value)


def _point(value, label, size):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        _fail("invalid_geometry", f"{label} 必须包含 {size} 个真实坐标。")
    result = [_number(v, label) for v in value]
    if size == 3 and abs(result[2]) > 1e-9:
        _fail("nonplanar_geometry", "仅支持世界 XY 平面零高程中心线，不会丢弃真实高程。")
    return result[:2]


def _normal(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        _fail("invalid_geometry", "圆弧和多段线必须包含真实法向。")
    normal = [_number(v, "法向") for v in value]
    if any(abs(a - b) > 1e-9 for a, b in zip(normal, (0, 0, 1))):
        _fail("nonplanar_geometry", "仅支持正向世界 XY 平面，不会重投影倾斜或反向 OCS。")


def _line(start, end):
    if math.dist(start, end) <= 1e-7:
        _fail("zero_length", "选择中存在零长或数值上不可用的中心线段。")
    return {"type": "line", "start": start, "end": end}


def _bulge_segment(start, end, bulge):
    # Bulge = tan(signed included angle / 4); retain clockwise and major arcs.
    if bulge == 0:
        return _line(start, end)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-7:
        _fail("zero_length", "多段线圆弧具有重合端点，不能确定真实圆弧。")
    factor = (1 / bulge - bulge) / 4
    center = [(start[0] + end[0]) / 2 - dy * factor,
              (start[1] + end[1]) / 2 + dx * factor]
    center = _point(center, "bulge 圆心", 2)
    radius = _number(length * (abs(bulge) + 1 / abs(bulge)) / 4, "bulge 半径")
    return {"type": "arc", "center": center, "radius": radius,
            "start_angle": math.atan2(start[1] - center[1], start[0] - center[0]),
            "end_angle": math.atan2(end[1] - center[1], end[0] - center[0]),
            "clockwise": bulge < 0}


def _segments(entity):
    kind = entity.get("type")
    names = {"line": "AcDbLine", "arc": "AcDbArc", "polyline": "AcDbPolyline"}
    if kind not in names or entity.get("object_name") != names[kind]:
        _fail("unsupported_selection", "选择只能包含 LINE、ARC 和开放 LWPOLYLINE；混入其他对象时整批拒绝。")
    if entity.get("is_2d_planar") is not True:
        _fail("nonplanar_geometry", "选择中存在未核验为世界 XY 零高程的对象。")
    if kind == "line":
        return [_line(_point(entity.get("start"), "LINE 起点", 3),
                      _point(entity.get("end"), "LINE 终点", 3))]
    _normal(entity.get("normal"))
    if kind == "arc":
        center = _point(entity.get("center"), "ARC 圆心", 3)
        radius = _number(entity.get("radius"), "ARC 半径")
        start = _number(entity.get("start_angle"), "ARC 起角", bound=math.tau)
        end = _number(entity.get("end_angle"), "ARC 终角", bound=math.tau)
        if (radius <= 0 or (end - start) % math.tau <= 1e-7
                or abs(end - start) >= math.tau - 1e-7):
            _fail("invalid_geometry", "道路圆弧需要正半径和大于零、小于整圆的角度。")
        if entity.get("angle_units") != "radians_ccw":
            _fail("invalid_geometry", "ARC 角度必须明确为弧度和逆时针方向。")
        for key, angle in (("start_point", start), ("end_point", end)):
            actual = _point(entity.get(key), f"ARC {key}", 3)
            expected = [center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle)]
            if math.dist(actual, expected) > max(1e-7, radius * 1e-9):
                _fail("inconsistent_geometry", "ARC 真实端点与圆心、角度不一致，需重新读取。")
        return [{"type": "arc", "center": center, "radius": radius,
                 "start_angle": start, "end_angle": end, "clockwise": False}]
    if entity.get("closed") is not False:
        _fail("closed_polyline", "闭合多段线可能是地块或道路边界，不能作为开放道路中心线导入。")
    if abs(_number(entity.get("elevation"), "多段线标高")) > 1e-9:
        _fail("nonplanar_geometry", "多段线标高不为零，不会静默丢弃。")
    points, bulges = entity.get("points"), entity.get("bulges")
    if (not isinstance(points, list) or not 2 <= len(points) <= 1001
            or not isinstance(bulges, list) or len(bulges) != len(points)):
        _fail("invalid_geometry", "开放多段线需要完整的 2–1001 个顶点及逐顶点 bulge。")
    points = [_point(p, "多段线顶点", 2) for p in points]
    bulges = [_number(b, "bulge") for b in bulges]
    if math.dist(points[0], points[-1]) <= 1e-7:
        _fail("closed_polyline", "多段线首尾重合，不能自动视为开放中心线。")
    return [_bulge_segment(points[i], points[i + 1], bulges[i]) for i in range(len(points) - 1)]


def from_inspection(snapshot: dict, *, confirmed_centerlines: bool = False) -> dict:
    """Return {spec, source, synthetic: False}, or raise CadImportError.

    ``synthetic`` describes the geometry's import origin, not the historical
    origin/accuracy of the selected drawing. The input snapshot is not mutated.
    Every selected object must pass; no objects are silently skipped or joined.
    """
    if confirmed_centerlines is not True:
        _fail("centerline_confirmation_required", "请显式确认当前所选对象是道路中心线。")
    if not isinstance(snapshot, dict) or snapshot.get("connected") is not True:
        _fail("cad_not_connected", "需要已连接 CAD 的真实读取结果。")
    document, selection = snapshot.get("document"), snapshot.get("selection")
    if not isinstance(document, dict) or not isinstance(document.get("identity"), str) or not document["identity"]:
        _fail("missing_document", "读取结果缺少当前文档身份。")
    if snapshot.get("active_document_unchanged_during_read") is not True:
        _fail("document_changed", "读取期间活动图纸发生变化或未完成一致性检查，请重新读取。")
    if (snapshot.get("truncated") is not False or snapshot.get("layers_truncated") is not False
            or not isinstance(selection, dict) or selection.get("truncated") is not False):
        _fail("truncated_snapshot", "图纸或选择集读取不完整，请提高读取上限或缩小图纸后重新读取。")
    if selection.get("source") != "PickfirstSelectionSet":
        _fail("invalid_selection_source", "仅接受实际 Pickfirst 选择集，不会用整图对象替代空选择。")
    entities, count = selection.get("entities"), selection.get("count")
    if (not isinstance(entities, list) or type(count) is not int or count != len(entities)
            or not 1 <= count <= 200):
        _fail("invalid_selection_count", "需要完整且非空的 1–200 个中心线选择对象。")
    roads, origins, handles, warnings = [], [], set(), []
    for index, entity in enumerate(entities, 1):
        if not isinstance(entity, dict):
            _fail("invalid_geometry", "选择集对象必须包含完整几何。")
        handle = entity.get("handle")
        if not isinstance(handle, str) or not re.fullmatch(r"[0-9A-Fa-f]{1,32}", handle):
            _fail("invalid_handle", "选择对象缺少有效 CAD handle。")
        if handle.upper() in handles:
            _fail("duplicate_handle", "选择中存在重复 CAD handle，请重新读取。")
        handles.add(handle.upper())
        segments = _segments(entity)
        road_id = "cad-" + handle.upper()
        layer = entity.get("layer")
        if not isinstance(layer, str):
            _fail("invalid_geometry", "选择对象缺少真实图层。")
        roads.append({"id": road_id, "name": f"CAD 中心线 {index}", "segments": segments,
                      "left_width": None, "right_width": None, "level": 0, "junction_type": None})
        origins.append({"road_id": road_id, "handle": handle, "layer": layer,
                        "object_name": entity["object_name"], "segment_count": len(segments)})
        if len(segments) > 1 and any(s["type"] == "arc" for s in segments):
            warnings.append(f"{road_id} 保留了真实复合线形；当前生成器不支持多段含弧道路，需人工拆分并校核连接。")
    if sum(len(r["segments"]) for r in roads) > 1000:
        _fail("too_many_segments", "选择共超过 1000 个中心线段，请缩小选择。")
    insunits = document.get("units")
    units = {6: "m", 4: "mm", 5: "cm", 2: "ft", 1: "in"}.get(insunits) if type(insunits) is int else None
    required = ["coordinate_reference", "left_width", "right_width", "junction_radius", "qa_tolerance", "roads[*].junction_type"]
    if units is None:
        required.insert(0, "units")
        warnings.append("INSUNITS 未声明受支持的单位；坐标未缩放，需人工核实单位。")
    warnings.append("CAD 世界 XY 坐标不等于已知地理坐标系；请核实坐标基准、道路宽度、路口形式、半径和校核容差。")
    spec = {"units": units, "coordinate_reference": None, "left_width": None, "right_width": None,
            "junction_radius": None, "qa_tolerance": None, "roads": roads,
            "constraints": [], "context_entities": [],
            "_import": {"kind": "cad_pickfirst", "actual_geometry_reread": True,
                        "required_fields": required, "warnings": warnings,
                        "constraints_status": "not_imported_or_verified"}}
    source = {"kind": "cad_pickfirst", "document_identity": document["identity"],
              "document_id": document.get("document_id"), "handles": [e["handle"] for e in origins],
              "entities": origins, "insunits": insunits if type(insunits) is int else None,
              "confirmed_centerlines": True, "active_document_unchanged_during_read": True,
              "coordinates_scaled": False, "writes_performed": False}
    source["selection_sha256"] = hashlib.sha256(json.dumps(
        {"document_identity": source["document_identity"], "insunits": source["insunits"],
         "origins": origins, "roads": roads}, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return {"spec": spec, "source": source, "synthetic": False}
