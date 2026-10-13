"""Original, deterministic planning-parcel geometry and arithmetic.

This module implements public mathematical operations from first principles;
it contains no proprietary planning-software code, tables, icons or templates.
All coordinates must be metres in a declared local Cartesian plane. Indicators
are supplied by the caller and remain unverified planning assumptions.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from pathlib import Path

from shapely import to_wkb
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
from shapely.validation import explain_validity

ATTRIBUTE_FIELDS = ("land_use_code", "land_use_name", "far_max", "coverage_max_pct",
                    "green_min_pct", "height_max_m")
CSV_FIELDS = ("parcel_id", "land_use_code", "land_use_name", "area_m2", "area_ha",
              "share_of_boundary_pct", "far_max", "max_gfa_m2", "coverage_max_pct",
              "max_building_footprint_m2", "green_min_pct", "min_green_area_m2",
              "height_max_m", "indicator_status", "geometry_sha256", "attribute_binding_status")
GEOMETRY_BINDING_ALGORITHM = "sha256_normalized_wkb_2d_le_v1"
LAYER_COLORS = {"PARCEL_BOUNDARY": 3, "PARCEL_HOLE": 2, "SITE_BOUNDARY": 7,
                "SITE_EXCLUSION": 2, "PARCEL_LABEL": 2, "PARCEL_ROAD": 8,
                "PARCEL_ROAD_CENTER": 1, "CONTROL_FRAME": 7, "CONTROL_TEXT": 2}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _printable(value, limit=80):
    return isinstance(value, str) and 0 < len(value) <= limit and all(ord(c) >= 32 for c in value)


def _polygon(value, name):
    """Accept {outer: [[x,y],...], holes: [...]} or an outer-ring list."""
    if isinstance(value, list):
        value = {"outer": value}
    if not isinstance(value, dict) or "outer" not in value:
        raise ValueError(f"{name} 必须是 outer/holes 多边形对象或外环点列表。")
    holes = value.get("holes", [])
    if not isinstance(holes, list):
        raise ValueError(f"{name}.holes 必须是孔洞环列表。")
    rings = []
    for index, ring in enumerate([value["outer"], *holes]):
        if not isinstance(ring, list) or not 3 <= len(ring) <= 10000:
            raise ValueError(f"{name} 第 {index} 个环需要 3–10000 个顶点。")
        if any(not isinstance(p, (list, tuple)) or len(p) != 2 or
               any(not _number(v) or abs(v) > 1e7 for v in p) for p in ring):
            raise ValueError(f"{name} 坐标必须是两个绝对值不超过 1e7 的有限数。")
        pts = [tuple(float(v) for v in p) for p in ring]
        if pts[0] == pts[-1]:
            pts.pop()
        if len(set(pts)) < 3 or any(a == b for a, b in zip(pts, pts[1:] + pts[:1])):
            raise ValueError(f"{name} 含不足三个不同顶点或连续重复点。")
        rings.append(pts)
    geom = Polygon(rings[0], rings[1:])
    if geom.is_empty or not geom.is_valid or geom.area <= 0:
        raise ValueError(f"{name} 无有效面积或拓扑非法：{explain_validity(geom)}；不会自动修复。")
    return geom


def _polygons(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [p for child in geom.geoms for p in _polygons(child)]
    return []


def _coordinates(poly):
    return {"outer": [list(p) for p in poly.exterior.coords[:-1]],
            "holes": [[list(p) for p in ring.coords[:-1]] for ring in poly.interiors]}


def _sort_key(poly):
    # North-to-south centroid, then west-to-east; WKB breaks exact geometric ties.
    return (-poly.centroid.y, poly.centroid.x, poly.bounds, poly.normalize().wkb_hex)


def _geometry_sha256(poly):
    """Exact geometry identity; ring direction/start/order are canonicalized.

    No rounding, area proxy, buffering, snapping or geometric repair is used.
    Extra collinear vertices and numerically different coordinates may require
    re-confirmation even if their visual appearance is similar.
    """
    payload = to_wkb(poly.normalize(), hex=False, output_dimension=2,
                     byte_order=1, include_srid=False, flavor="iso")
    return hashlib.sha256(payload).hexdigest()


def _attributes(value, context, error):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        error("invalid_attributes", "地块 attributes 必须是对象。", parcel_id=context)
        return {}
    output = {}
    for key in ATTRIBUTE_FIELDS:
        v = value.get(key)
        if v is None:
            output[key] = None
        elif key in ("land_use_code", "land_use_name"):
            if not _printable(v):
                error("invalid_attribute", f"{key} 必须是 1–80 个可打印字符。", parcel_id=context)
            else:
                output[key] = v
        elif not _number(v) or v < 0 or (key.endswith("pct") and v > 100) or v > 1e7:
            error("invalid_attribute", f"{key} 必须为有限非负数；百分比不得超过 100。", parcel_id=context)
        else:
            output[key] = float(v)
    unknown = set(value) - set(ATTRIBUTE_FIELDS)
    if unknown:
        error("unknown_attribute", "存在未识别指标，不能默默忽略。", parcel_id=context, fields=sorted(unknown))
    return output


def generate(spec: dict) -> dict:
    """Return CAD entities, polygons, rows, metrics and explicit QA findings.

    Modes are selected explicitly: ``mode='roads'`` subtracts a union of flat-
    capped, mitred polyline buffers; ``mode='explicit'`` validates supplied
    parcels and accounts for the remainder as unallocated land. Road buffering
    is a land-accounting approximation, not engineered intersection geometry.
    """
    result = {"entities": [], "bounds": [0, 0, 1, 1],
              "report": {"errors": [], "warnings": [], "checks": []}, "metrics": {},
              "spec": copy.deepcopy(spec) if isinstance(spec, dict) else {}, "parcels": [],
              "geometry_bindings": {}, "geometry_binding_algorithm": GEOMETRY_BINDING_ALGORITHM}
    report = result["report"]

    def issue(category, code, message, **context):
        report[category].append({"code": code, "message": message, **context})

    def error(code, message, **context):
        issue("errors", code, message, **context)

    if not isinstance(spec, dict):
        error("invalid_spec", "参数必须是 JSON 对象。")
        return result
    if spec.get("kind") != "regulatory_parcels":
        error("invalid_kind", "kind 必须是 regulatory_parcels。")
    if spec.get("units") != "m":
        error("units_required", "只接受明确的米单位 m；不得仅改单位标签替代坐标转换。")
    if spec.get("coordinate_reference") != "local_cartesian":
        error("unsupported_crs", "必须声明 local_cartesian；经纬度和未核实投影不能直接计算。")
    mode = spec.get("mode")
    if mode not in ("roads", "explicit"):
        error("mode_required", "mode 必须明确为 roads 或 explicit。")
    threshold = spec.get("sliver_threshold_m2", 10.0)
    if not _number(threshold) or threshold < 0:
        error("invalid_sliver_threshold", "小地块提示阈值必须是非负有限数，属于计算提示参数。")
    try:
        boundary = _polygon(spec.get("boundary"), "boundary")
    except ValueError as exc:
        error("invalid_boundary", str(exc))
        return result
    if report["errors"]:
        return result
    roads = spec.get("roads", [])
    if not isinstance(roads, list) or len(roads) > 200:
        error("invalid_roads", "roads 必须是最多 200 条道路的列表。")
        return result
    road_ids, road_buffers, road_lines = set(), [], []
    for i, road in enumerate(roads):
        if not isinstance(road, dict):
            error("invalid_road", "每条道路必须为对象。", road_index=i)
            continue
        rid = road.get("id")
        if not _printable(rid) or rid in road_ids:
            error("duplicate_or_invalid_id", "道路 ID 必须非空且唯一。", road_index=i)
            continue
        road_ids.add(rid)
        pts, width = road.get("centerline"), road.get("total_width_m")
        if not _number(width) or not 0 < width <= 1e6:
            error("invalid_road_width", "total_width_m 必须是正有限数，且不超过 1e6。", road_id=rid)
            continue
        if (not isinstance(pts, list) or not 2 <= len(pts) <= 10000 or
            any(not isinstance(p, (list, tuple)) or len(p) != 2 or
                any(not _number(v) or abs(v) > 1e7 for v in p) for p in pts)):
            error("invalid_centerline", "centerline 需要 2–10000 个有限二维坐标。", road_id=rid)
            continue
        line = LineString(pts)
        if line.length <= 0 or not line.is_simple or any(a == b for a, b in zip(line.coords, list(line.coords)[1:])):
            error("invalid_centerline", "道路中心线不能零长、自交或含连续重复点。", road_id=rid)
            continue
        corridor = line.buffer(float(width) / 2, cap_style=2, join_style=2, mitre_limit=5).intersection(boundary)
        if corridor.area <= 0:
            error("road_outside_boundary", "道路用地与有效边界没有面积相交。", road_id=rid)
            continue
        road_buffers.append(corridor)
        road_lines.append((rid, line))
    if report["errors"]:
        return result
    road_union = unary_union(road_buffers) if road_buffers else Polygon()
    parcel_geoms = []
    if mode == "roads":
        if spec.get("parcels"):
            error("conflicting_modes", "roads 模式不接受显式 parcels；请选择一种地块来源。")
        attr_map = spec.get("parcel_attributes", {})
        if not isinstance(attr_map, dict):
            error("invalid_attributes", "parcel_attributes 必须是地块 ID 到指标对象的映射。")
            attr_map = {}
        remainder = boundary.difference(road_union)
        for index, poly in enumerate(sorted(_polygons(remainder), key=_sort_key), 1):
            pid = f"P{index:03d}"
            parcel_geoms.append((pid, poly, _attributes(attr_map.get(pid), pid, error)))
        unknown = set(attr_map) - {p[0] for p in parcel_geoms}
        if unknown:
            error("unknown_parcel_id", "指标映射引用了本次未生成的地块 ID。", parcel_ids=sorted(unknown))
        issue("warnings", "generated_id_scope", "P 编号按质心由北向南、同纬由西向东排序；几何改变后可能重排，属性须随版本复核。")
    else:
        if spec.get("parcel_attributes"):
            error("conflicting_modes", "explicit 模式请把指标放入每块 attributes，不接受 parcel_attributes。")
        parcels = spec.get("parcels")
        if not isinstance(parcels, list) or not 1 <= len(parcels) <= 1000:
            error("invalid_parcels", "explicit 模式需要 1–1000 块显式地块。")
            return result
        parcel_ids = set()
        for index, parcel in enumerate(parcels):
            if not isinstance(parcel, dict):
                error("invalid_parcel", "每块地块必须为对象。", parcel_index=index)
                continue
            pid = parcel.get("id")
            if not _printable(pid) or pid in parcel_ids:
                error("duplicate_or_invalid_id", "地块 ID 必须非空且唯一。", parcel_index=index)
                continue
            parcel_ids.add(pid)
            try:
                poly = _polygon(parcel.get("polygon"), f"parcel {pid}")
            except ValueError as exc:
                error("invalid_parcel_polygon", str(exc), parcel_id=pid)
                continue
            if not boundary.covers(poly):
                error("parcel_outside_boundary", "地块越出有效边界或侵入边界孔洞。", parcel_id=pid)
            if poly.intersection(road_union).area > 0:
                error("parcel_road_overlap", "显式地块与道路用地相交。", parcel_id=pid)
            for other_id, other_poly, _ in parcel_geoms:
                overlap = poly.intersection(other_poly).area
                if overlap > 0:
                    error("parcel_overlap", "显式地块面积重叠；共边允许。", parcel_id=pid,
                          other_parcel_id=other_id, overlap_area_m2=overlap)
            parcel_geoms.append((pid, poly, _attributes(parcel.get("attributes"), pid, error)))
        parcel_geoms.sort(key=lambda p: (_sort_key(p[1]), p[0]))
    if report["errors"]:
        return result
    if len(parcel_geoms) > 1000:
        error("too_many_parcels", "生成地块超过 1000 块；请缩小计算范围。")
        return result
    geometry_bindings = {pid: _geometry_sha256(poly) for pid, poly, _ in parcel_geoms}
    result["geometry_bindings"] = geometry_bindings
    # The presence of the key is intentional: {} means enforce binding, not
    # opt out. Fresh caller-assigned parameters omit the key altogether.
    has_bindings = "attribute_geometry_bindings" in spec
    bindings = spec.get("attribute_geometry_bindings") if has_bindings else {}
    if has_bindings and (not isinstance(bindings, dict) or
            any(not _printable(pid) or not isinstance(digest, str) or len(digest) != 64 or
                any(c not in "0123456789abcdef" for c in digest) for pid, digest in bindings.items())):
        error("attribute_binding_mismatch", "attribute_geometry_bindings 必须是地块 ID 到 64 位小写 SHA-256 的映射。",
              reason="invalid_binding_schema")
        return result
    assigned_ids = [pid for pid, _, attrs in parcel_geoms if any(v is not None for v in attrs.values())]
    if has_bindings:
        for pid in assigned_ids:
            if bindings.get(pid) != geometry_bindings[pid]:
                error("attribute_binding_mismatch", "指标绑定的地块几何缺失或已改变；必须重新确认归属，不能沿用旧编号自动套用。",
                      parcel_id=pid, expected_geometry_sha256=bindings.get(pid),
                      actual_geometry_sha256=geometry_bindings[pid],
                      reason="missing_binding" if pid not in bindings else "geometry_changed")
        if report["errors"]:
            return result
        issue("checks", "attribute_geometry_bound", "所有非空指标已与当前精确地块几何签名匹配。",
              parcel_ids=assigned_ids, algorithm=GEOMETRY_BINDING_ALGORITHM)
    elif assigned_ids:
        issue("warnings", "caller_assigned", "首次指标由调用者明确按当前编号赋予，尚未绑定几何；确认当前归属后应调用 bind_attributes 保存签名。",
              parcel_ids=assigned_ids, attribute_binding_status="caller_assigned")
    parcel_union = unary_union([p[1] for p in parcel_geoms]) if parcel_geoms else Polygon()
    unallocated = boundary.difference(unary_union([road_union, parcel_union]))
    total_parcel_area = sum(p[1].area for p in parcel_geoms)
    tolerance = max(1e-7, boundary.area * 1e-10)
    residual = boundary.area - road_union.area - total_parcel_area - unallocated.area
    if abs(residual) > tolerance:
        error("area_conservation", "面积守恒校核失败。", residual_m2=residual, tolerance_m2=tolerance)
        return result
    entities = result["entities"]

    def emit(kind, layer, **attrs):
        entities.append({"id": f"parcel-entity-{len(entities) + 1:05d}", "type": kind, "layer": layer, **attrs})

    def polygon_entities(poly, outer_layer, hole_layer, **attrs):
        emit("polyline", outer_layer, points=[list(p) for p in poly.exterior.coords[:-1]], closed=True, **attrs)
        for index, ring in enumerate(poly.interiors):
            emit("polyline", hole_layer, points=[list(p) for p in ring.coords[:-1]], closed=True,
                 ring_role="hole", hole_index=index, **attrs)

    polygon_entities(boundary, "SITE_BOUNDARY", "SITE_EXCLUSION", geometry_role="site")
    for poly in _polygons(road_union):
        polygon_entities(poly, "PARCEL_ROAD", "PARCEL_ROAD", geometry_role="road_land")
    for rid, line in road_lines:
        clipped = line.intersection(boundary)
        parts = list(clipped.geoms) if hasattr(clipped, "geoms") else [clipped]
        for part in parts:
            if part.geom_type == "LineString" and part.length > 0:
                emit("polyline", "PARCEL_ROAD_CENTER", points=[list(p) for p in part.coords], closed=False, road_id=rid)
    rows, missing, slivers = [], [], []
    for pid, poly, attrs in parcel_geoms:
        polygon_entities(poly, "PARCEL_BOUNDARY", "PARCEL_HOLE", parcel_id=pid)
        area = float(poly.area)
        assigned = any(v is not None for v in attrs.values())
        row = {"parcel_id": pid, **attrs, "area_m2": area, "area_ha": area / 10000,
               "share_of_boundary_pct": area / boundary.area * 100,
               "max_gfa_m2": None if attrs["far_max"] is None else area * attrs["far_max"],
               "max_building_footprint_m2": None if attrs["coverage_max_pct"] is None else area * attrs["coverage_max_pct"] / 100,
               "min_green_area_m2": None if attrs["green_min_pct"] is None else area * attrs["green_min_pct"] / 100,
               "indicator_status": "user_supplied_unverified" if assigned else "not_supplied",
               "geometry_sha256": geometry_bindings[pid],
               "attribute_binding_status": ("geometry_bound" if has_bindings else "caller_assigned") if assigned else "not_supplied"}
        rows.append(row)
        missing_fields = [k for k in ATTRIBUTE_FIELDS if attrs[k] is None]
        if missing_fields:
            missing.append({"parcel_id": pid, "fields": missing_fields})
        if area < threshold:
            slivers.append({"parcel_id": pid, "area_m2": area})
        label = f"{pid} / {area:.2f} m2"
        fitted = _fit_inside(poly, label)
        if fitted:
            pos, height, envelope = fitted
            emit("text", "PARCEL_LABEL", position=pos, text=label, height=height,
                 parcel_id=pid, label_envelope=envelope)
        else:
            issue("warnings", "label_does_not_fit", "地块过窄，图内不放文字；请使用指标表或独立图则。", parcel_id=pid)
        result["parcels"].append({"id": pid, "polygon": _coordinates(poly), "data": row,
                                  "geometry_sha256": geometry_bindings[pid]})
    issue("checks", "valid_polygons", "输入多边形有效；未使用 buffer(0) 或其他自动拓扑修复。")
    issue("checks", "road_union", "道路用地先求并集再计量，共享交叉口不重复计面积。",
          sum_individual_road_area_m2=sum(p.area for p in road_buffers), union_road_area_m2=road_union.area)
    issue("checks", "area_conservation", "有效边界面积 = 道路并集 + 地块面积 + 未分配面积。",
          residual_m2=residual, tolerance_m2=tolerance)
    issue("checks", "parcel_label_envelopes", "文字按保守字符宽度估算框放入地块内部；最终字体尺寸应在 CAD 中复核。")
    issue("warnings", "planning_scope", "地块分割及指标乘法不验证规划合法性、建筑退界、建筑布置、交通或容量可行性；不存在自动规范合规结论。")
    if roads:
        issue("warnings", "road_buffer_scope", "道路为中心线半宽、平头端部、斜接连接的计算走廊，裁到有效边界；没有设计交叉口圆角、展宽或立交。")
    if missing:
        issue("warnings", "missing_indicators", "缺少的用地及控制指标保留为空，不生成规范默认值。", parcels=missing)
    if slivers:
        issue("warnings", "small_parcels", "小地块全部保留；阈值仅为计算提示，并非最小合法地块面积。",
              threshold_m2=threshold, parcels=slivers)
    if unallocated.area > tolerance:
        issue("warnings", "unallocated_land", "显式地块未覆盖的剩余面积单独核算。", area_m2=unallocated.area)
    gross_area = Polygon(boundary.exterior).area
    if boundary.interiors:
        issue("warnings", "boundary_holes", "边界孔洞视为本次计算排除空间，不计入有效边界及面积占比分母；不推断其权属或用途。",
              excluded_area_m2=gross_area - boundary.area)
    result["metrics"] = {"length_unit": "m", "area_unit": "m2", "coordinate_reference": "local_cartesian",
        "boundary_area_m2": boundary.area, "boundary_gross_area_m2": gross_area,
        "boundary_holes_area_m2": gross_area - boundary.area, "road_area_m2": road_union.area,
        "parcel_area_m2": total_parcel_area, "unallocated_area_m2": unallocated.area,
        "area_conservation_residual_m2": residual, "area_tolerance_m2": tolerance,
        "parcel_count": len(parcel_geoms), "road_count": len(roads), "small_parcel_count": len(slivers),
        "sliver_threshold_m2": threshold, "rows": rows, "entity_count": len(entities),
        "share_denominator": "boundary_area_m2_excluding_holes",
        "max_gfa_meaning": "parcel_area_m2 * user_far_max; a conditional upper limit, not actual floor area",
        "indicator_compliance": "not_evaluated"}
    result["bounds"] = list(boundary.bounds)
    result["road_polygons"] = [_coordinates(p) for p in _polygons(road_union)]
    result["unallocated_polygons"] = [_coordinates(p) for p in _polygons(unallocated)]
    return result


def bind_attributes(spec, result):
    """Return a new spec binding indicators to an explicitly confirmed preview.

    Call ONLY after the user/caller confirms current parcel-to-indicator
    assignments. Do not run automatically after a road, boundary or parcel
    edit: that would erase the evidence that geometry changed. The supplied
    result must be a complete, error-free preview of precisely the current
    geometry; old previews and individual control sheets are rejected.

    Re-confirmation flow: preserve the saved spec, make an unbound candidate
    by removing attribute_geometry_bindings, generate and present it, obtain
    the caller's explicit assignment confirmation, then call this function
    with that candidate and its result. Attribute changes alone can keep the
    saved bindings when the geometry is unchanged.
    """
    _ready(result)
    candidate = copy.deepcopy(spec)
    if not isinstance(candidate, dict):
        raise ValueError("绑定参数必须为对象。")
    candidate.pop("attribute_geometry_bindings", None)
    current = generate(candidate)
    if current["report"]["errors"]:
        raise ValueError("当前参数无法生成有效地块，不能绑定指标。")
    expected = current["geometry_bindings"]
    if (not expected or expected != result.get("geometry_bindings") or
            {p["id"]: p.get("geometry_sha256") for p in result.get("parcels", [])} != expected or
            any(_geometry_sha256(_polygon(p["polygon"], "confirmed parcel")) != expected[p["id"]]
                for p in result.get("parcels", []))):
        raise ValueError("确认结果与当前地块几何不一致；请重新生成预览并确认归属。")
    current_attributes = {p["id"]: {key: p["data"].get(key) for key in ATTRIBUTE_FIELDS}
                          for p in current["parcels"]}
    confirmed_attributes = {p["id"]: {key: p.get("data", {}).get(key) for key in ATTRIBUTE_FIELDS}
                            for p in result["parcels"]}
    if current_attributes != confirmed_attributes:
        raise ValueError("确认结果与当前地块指标不一致；请重新预览指标后确认。")
    candidate["attribute_geometry_bindings"] = copy.deepcopy(expected)
    return candidate


def _fit_inside(poly, text):
    """Keep a conservative label box out of holes and outside boundaries."""
    anchor = poly.representative_point()
    height = min(2.5, math.sqrt(poly.area) / 12)
    text_units = sum(1.15 if ord(c) > 127 else 0.85 for c in text)
    while height >= 0.025:
        width = max(1, text_units) * height
        x, y = anchor.x - width / 2, anchor.y - height / 2
        envelope = [x - height * .1, y - height * .3, x + width + height * .1, y + height * 1.3]
        if poly.covers(box(*envelope)):
            return [x, y], height, envelope
        height *= .8
    return None


def _ready(result):
    if not isinstance(result, dict) or result.get("report", {}).get("errors"):
        raise ValueError("地块结果存在错误，不能导出。")
    if result.get("spec", {}).get("kind") != "regulatory_parcels" or result["spec"].get("units") != "m":
        raise ValueError("只接受声明米单位的 regulatory_parcels 结果。")


def _new_path(path):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"目标已存在，请使用新文件名：{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def export_parcels_csv(result, path):
    """UTF-8 BOM table; blanks mean missing data, never zero or compliance.

    Formula-like user strings are prefixed with an apostrophe for spreadsheet
    viewers. Exact strings remain available in the local-coordinate JSON.
    """
    _ready(result)
    path = _new_path(path)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for source_row in result["metrics"]["rows"]:
            row = dict(source_row)
            for key, value in row.items():
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    row[key] = "'" + value
            writer.writerow(row)


def export_parcels_json(result, path):
    """Explicit local-coordinate JSON. Deliberately not RFC 7946 GeoJSON."""
    _ready(result)
    payload = {"format": "planningworkbench_local_parcels_v1", "units": "m",
               "coordinate_reference": "local_cartesian", "is_geojson": False,
               "parcels": result["parcels"], "metrics": result["metrics"], "report": result["report"],
               "geometry_bindings": result["geometry_bindings"],
               "geometry_binding_algorithm": result["geometry_binding_algorithm"],
               "source_spec": result["spec"]}
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    _new_path(path).write_text(text, encoding="utf-8")


def export_parcels_dxf(result, path):
    """Editable, metre-unit linework and TEXT with retained hole-ring metadata."""
    _ready(result)
    from app.cad import validate_entities
    validate_entities(result["entities"])
    path = _new_path(path)
    import ezdxf
    doc = ezdxf.new("R2013")
    doc.units = 6
    doc.header["$MEASUREMENT"] = 1
    doc.appids.add("PLANNINGWB")
    doc.styles.new("PW_CN", dxfattribs={"font": "simhei.ttf"})
    msp = doc.modelspace()
    for name, color in LAYER_COLORS.items():
        doc.layers.new(name, dxfattribs={"color": color})
    for item in result["entities"]:
        attrs = {"layer": item["layer"]}
        if item["type"] == "polyline":
            entity = msp.add_lwpolyline(item["points"], close=item.get("closed", False), dxfattribs=attrs)
        elif item["type"] == "line":
            entity = msp.add_line(item["start"], item["end"], dxfattribs=attrs)
        else:
            entity = msp.add_text(item["text"], dxfattribs={**attrs, "height": item["height"], "insert": item["position"], "style": "PW_CN"})
        entity.set_xdata("PLANNINGWB", [(1000, item["id"]), (1000, item.get("parcel_id", "")),
                                     (1000, item.get("ring_role", "outer_or_other"))])
    payload = json.dumps(result["spec"], ensure_ascii=False, allow_nan=False)
    doc.rootdict.add_xrecord("PLANNINGWB_PARCELSPEC").reset([(1, payload[i:i + 200]) for i in range(0, len(payload), 200)])
    doc.saveas(path)


def build_control_sheet(result, parcel_id):
    """A3 landscape model-space sheet in metres, using original line/text art.

    The parcel diagram is scaled and clearly labelled; its coordinates are NOT
    the source engineering coordinates. The source polygon stays in ``data``.
    """
    _ready(result)
    parcel = next((p for p in result["parcels"] if p["id"] == parcel_id), None)
    if parcel is None:
        raise ValueError(f"不存在地块：{parcel_id}")
    output = {"entities": [], "bounds": [0, 0, .42, .297], "report": {"errors": [], "warnings": [], "checks": []},
              "spec": copy.deepcopy(result["spec"]), "data": copy.deepcopy(parcel), "metrics": {"rows": [copy.deepcopy(parcel["data"])]},
              "parcels": [copy.deepcopy(parcel)],
              "geometry_bindings": {parcel_id: parcel["geometry_sha256"]},
              "geometry_binding_algorithm": GEOMETRY_BINDING_ALGORITHM}
    entities = output["entities"]

    def emit(kind, layer, **attrs):
        entities.append({"id": f"sheet-{len(entities) + 1:04d}", "type": kind, "layer": layer, **attrs})

    def label(x, y, text, height=.003, max_width=.16):
        width_units = sum(1.15 if ord(c) > 127 else .85 for c in text)
        height = min(height, max_width / max(width_units, 1))
        emit("text", "CONTROL_TEXT", position=[x, y], text=text, height=height)

    emit("polyline", "CONTROL_FRAME", points=[[.01, .01], [.41, .01], [.41, .287], [.01, .287]], closed=True)
    for y in (.259, .06):
        emit("line", "CONTROL_FRAME", start=[.01, y], end=[.41, y])
    emit("line", "CONTROL_FRAME", start=[.243, .06], end=[.243, .259])
    label(.019, .273, f"地块控制指标教学图则  {parcel_id}", .005, .365)
    poly = _polygon(parcel["polygon"], "parcel")
    minx, miny, maxx, maxy = poly.bounds
    raw_scale = max((maxx - minx) / .205, (maxy - miny) / .16)
    exponent = 10 ** math.floor(math.log10(raw_scale))
    map_scale = next(v * exponent for v in (1, 2, 2.5, 5, 10) if v * exponent >= raw_scale)
    offset = [.02 + (.21 - (maxx - minx) / map_scale) / 2, .09 + (.16 - (maxy - miny) / map_scale) / 2]
    for index, ring in enumerate([poly.exterior, *poly.interiors]):
        pts = [[offset[0] + (x - minx) / map_scale, offset[1] + (y - miny) / map_scale] for x, y in ring.coords[:-1]]
        emit("polyline", "PARCEL_BOUNDARY" if index == 0 else "PARCEL_HOLE", points=pts, closed=True,
             parcel_id=parcel_id, ring_role="outer" if index == 0 else "hole")
    label(.021, .071, f"示意比例 1:{map_scale:g}；北向为 +Y（非实测真北）", .003, .21)
    row = parcel["data"]
    values = [
        ("地块编号", parcel_id), ("用地代码", row["land_use_code"]), ("用地名称", row["land_use_name"]),
        ("净地块面积 m2", f"{row['area_m2']:.2f}"), ("面积 ha", f"{row['area_ha']:.4f}"),
        ("容积率上限", row["far_max"]), ("计容面积上限 m2", row["max_gfa_m2"]),
        ("建筑密度上限 %", row["coverage_max_pct"]), ("绿地率下限 %", row["green_min_pct"]),
        ("高度上限 m", row["height_max_m"])]
    for index, (name, value) in enumerate(values):
        y = .243 - index * .018
        text = "待输入" if value is None else f"{value:g}" if isinstance(value, (int, float)) else str(value)
        label(.251, y, f"{name}: {text}", .003, .15)
    label(.019, .044, "指标来自用户输入；计容面积上限=净地块面积×容积率上限，不是实际建筑面积。", .003, .385)
    label(.019, .029, "未校核法定规划、退界、限高、日照或配套容量。孔洞为空间排除，不推断权属。", .003, .385)
    label(.019, .016, "原创计算示例 | 图框使用米单位：0.420×0.297 m；图内几何已缩放，勿作为实测底图。", .0025, .385)
    output["metrics"].update({"entity_count": len(entities), "sheet_size_m": [.42, .297],
                              "map_scale_denominator": map_scale, "indicator_compliance": "not_evaluated"})
    output["report"]["warnings"] = [{"code": "sheet_scope", "message": "图则为原创教学图框；地块示意按注明比例缩放，未验证规划合规性。"}]
    return output


def get_example():
    """Load the versioned original 240 x 180 metre teaching fixture."""
    path = Path(__file__).resolve().parents[1] / "examples" / "regulatory-parcels.json"
    return json.loads(path.read_text(encoding="utf-8"))
