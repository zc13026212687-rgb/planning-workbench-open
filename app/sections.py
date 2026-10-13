"""Original deterministic 2-D road cross sections; no terrain or design defaults.

Both side lists run from the reference centre outwards. slope_percent is dz / ds
where ds is positive outward distance: negative falls outward on BOTH sides.
CAD X is signed offset (left negative); CAD Y is absolute elevation in metres.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

ROLES = {"sidewalk", "cycleway", "carriageway", "median", "greenbelt"}
ROLE_LABELS = {"sidewalk": "步行", "cycleway": "骑行", "carriageway": "车行", "median": "分隔", "greenbelt": "绿带"}


def _fit_label(text, x0, x1, preferred_height):
    """Place LEFT-aligned TEXT inside its component without CAD alignment flags.

    Reserve 1.2 em per character, including ASCII, rather than assuming narrow
    Latin glyphs or a particular CAD font. The remaining 14% is a side margin.
    This conservative layout estimate still needs the actual CAD font check.
    """
    width = x1 - x0
    em_width = 1.2 * max(1, len(text))
    height = min(preferred_height, width * 0.86 / em_width)
    estimated_width = em_width * height
    return x0 + (width - estimated_width) / 2, height


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def generate(spec: dict) -> dict:
    result = {"entities": [], "bounds": [0, 0, 1, 1], "report": {"errors": [], "warnings": [], "checks": []},
              "metrics": {}, "spec": copy.deepcopy(spec) if isinstance(spec, dict) else {}}
    report, entities = result["report"], result["entities"]

    def error(code, message, **extra):
        report["errors"].append({"code": code, "message": message, **extra})

    if not isinstance(spec, dict):
        error("invalid_spec", "横断面输入必须为 JSON 对象。")
        return result
    if spec.get("kind") == "road_longitudinal_section":
        error("needs_input", "纵断面尚未实现；需要已确认的桩号—地面高程、设计控制高程及坡度/竖曲线设计条件。不能用横断面或虚构地形代替。")
        result["status"] = "needs_input"
        return result
    if spec.get("kind") != "road_cross_section":
        error("invalid_kind", "横断面 kind 必须为 road_cross_section。")
    if spec.get("units") != "m":
        error("units_required", "横断面首版只接受米；须明确转换全部宽度和高程，不能只改单位标签。")
    if spec.get("coordinate_reference") != "local_cartesian":
        error("unsupported_crs", "横断面坐标为局部偏距—高程，coordinate_reference 必须为 local_cartesian。")
    elevation = spec.get("reference_elevation")
    if not _finite(elevation) or abs(elevation) > 1e7:
        error("reference_elevation_required", "必须填写有限的中心基准高程，数值绝对值不大于 1e7 米。")
    if spec.get("slope_convention") != "outward_rise_percent":
        error("slope_convention_required", "请确认 slope_convention=outward_rise_percent：两侧负值均向外下降，正值均向外上升。")
    components = spec.get("components")
    if not isinstance(components, list) or not 1 <= len(components) <= 100:
        error("components_required", "需要 1–100 个明确宽度、顺序、横坡的组成部分。")
        return result
    ids, orders = set(), {"left": set(), "right": set()}
    for index, c in enumerate(components):
        if not isinstance(c, dict):
            error("invalid_component", "组成部分必须为对象。", component_index=index)
            continue
        cid, side, order = c.get("id"), c.get("side"), c.get("order")
        if not isinstance(cid, str) or not cid.strip() or cid in ids:
            error("invalid_component_id", "组成部分 ID 必须非空且唯一。", component_index=index)
        else:
            ids.add(cid)
        if not isinstance(side, str) or side not in orders:
            error("invalid_side", "side 必须为 left 或 right。", component_id=cid)
        elif isinstance(order, bool) or not isinstance(order, int) or order < 0 or order in orders[side]:
            error("invalid_order", "order 必须为本侧唯一的非负整数，由中心向外递增。", component_id=cid)
        else:
            orders[side].add(order)
        if not _finite(c.get("width")) or not 0 < c["width"] <= 1e4:
            error("invalid_width", "每一组成宽度须为正有限数，且不大于 10000 米；这是计算边界，不是规范阈值。", component_id=cid)
        if not _finite(c.get("slope_percent")) or abs(c["slope_percent"]) > 100:
            error("invalid_slope", "横坡百分数必须明确填写且在 -100 至 100 内；这是计算边界，不是规范推荐值。", component_id=cid)
        if c.get("role") is not None and (not isinstance(c["role"], str) or c["role"] not in ROLES):
            error("invalid_role", "role 仅支持 sidewalk/cycleway/carriageway/median/greenbelt。", component_id=cid)
        if any(k in c for k in ("step_up", "curb_height", "thickness")):
            error("unsupported_structure", "首版只生成连续路表；台阶、缘石高度及结构层厚度不能被静默忽略。", component_id=cid)
    if report["errors"]:
        return result

    def emit(kind, layer, **attributes):
        entities.append({"id": f"section-{len(entities)+1:04d}", "type": kind, "layer": layer, **attributes})

    widths = {s: sum(c["width"] for c in components if c["side"] == s) for s in orders}
    total_width = sum(widths.values())
    height = max(0.1, min(total_width / 90, 0.4))
    endpoints, component_metrics, all_surface = {}, [], [[0.0, float(elevation)]]
    # Each side starts at the SAME explicitly supplied centre elevation.
    for side in ("left", "right"):
        x, z = 0.0, float(elevation)
        direction = -1 if side == "left" else 1
        for c in sorted((c for c in components if c["side"] == side), key=lambda c: c["order"]):
            end = [x + direction * c["width"], z + c["width"] * c["slope_percent"] / 100]
            start = [x, z]
            emit("line", "SECTION_SURFACE", start=start, end=end, component_id=c["id"], role=c.get("role"))
            component_metrics.append({"id": c["id"], "side": side, "role": c.get("role"), "width": c["width"],
                                      "slope_percent": c["slope_percent"], "inner_elevation": z, "outer_elevation": end[1]})
            all_surface.append(end)
            x, z = end
        endpoints[side] = [x, z]
    low = min(p[1] for p in all_surface)
    high = max(p[1] for p in all_surface)
    dim_y = low - height * 5
    annotations = []
    for entity in list(entities):
        a, b = entity["start"], entity["end"]
        c = next(c for c in components if c["id"] == entity["component_id"])
        emit("line", "SECTION_DIMENSION", start=[a[0], dim_y], end=[b[0], dim_y])
        for x in (a[0], b[0]):
            emit("line", "SECTION_DIMENSION", start=[x, dim_y - height * 0.3], end=[x, dim_y + height * 0.3])
        x0, x1 = sorted((a[0], b[0]))
        label = f"{ROLE_LABELS.get(c.get('role'), '组成')}{c['width']:g}m"
        slope = f"{c['slope_percent']:+g}%"
        label_x, label_height = _fit_label(label, x0, x1, height)
        slope_x, slope_height = _fit_label(slope, x0, x1, height * 0.8)
        emit("text", "SECTION_LABEL", position=[label_x, dim_y + height * 0.45],
             text=label, height=label_height, component_id=c["id"], annotation_kind="component_width")
        emit("text", "SECTION_LABEL", position=[slope_x, max(a[1], b[1]) + height],
             text=slope, height=slope_height, component_id=c["id"], annotation_kind="component_slope")
        annotations.append({"component_id": c["id"], "full_name": c.get("name", c["id"]),
                            "display_label": label, "slope_label": slope, "span": [x0, x1]})
    emit("line", "SECTION_CENTER", start=[0, dim_y - height], end=[0, high + height * 4])
    emit("text", "SECTION_LABEL", position=[-widths["left"], high + height * 5],
         text=f"Width={total_width:g}m; centre={elevation:g}m; XY=offset/elevation; slope outward (+up/-down)", height=height)
    emit("text", "SECTION_LABEL", position=[-widths["left"], dim_y - height * 3],
         text="Synthetic teaching / unverified engineering design" if spec.get("synthetic") else "User parameters / unverified engineering design", height=height)
    report["checks"].append({"code": "continuous_surface", "message": "各侧从共同中心高程逐段累加，横坡按向外距离计算；输出 1:1 偏距—高程。"})
    report["checks"].append({"code": "width_sum", "message": "组成宽度求和完成。", "left_width": widths["left"], "right_width": widths["right"], "total_width": total_width})
    report["checks"].append({"code": "component_annotations", "message": "图面使用适应组成宽度的短名称；完整名称及向外坡度含义保留在参数和此表。文字使用左对齐插入点，最终字框需以 CAD 字体回读核验。",
                             "slope_convention": "outward_rise_percent", "components": annotations})
    report["warnings"].append({"code": "section_scope", "message": "只生成用户参数定义的连续路表横断面；未自动设计缘石、结构层、排水、土方或纵断面，不代表规范符合性。"})
    result["metrics"] = {"component_count": len(components), "left_width": widths["left"], "right_width": widths["right"],
                         "total_width": total_width, "reference_elevation": elevation, "endpoints": endpoints,
                         "components": component_metrics, "length_unit": "m", "vertical_scale": 1,
                         "horizontal_scale": 1, "entity_count": len(entities)}
    # Include conservative label extents so preview does not crop their anchors.
    points = []
    for e in entities:
        if e["type"] == "line":
            points.extend([e["start"], e["end"]])
        else:
            x, y = e["position"]
            points.extend([[x, y], [x + len(e["text"]) * e["height"] * 0.65, y + e["height"]]])
    result["bounds"] = [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]
    return result


def export_section_dxf(result: dict, path: Path):
    """Preserve real 1:1 surface coordinates; CAD text dimensions are labels."""
    if result.get("report", {}).get("errors"):
        raise ValueError("存在横断面错误，不能导出。")
    if result.get("spec", {}).get("kind") != "road_cross_section" or result["spec"].get("units") != "m":
        raise ValueError("仅支持已声明米单位的横断面结果。")
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"目标已存在，请另存：{path.name}")
    import ezdxf
    doc = ezdxf.new("R2013")
    doc.units = 6
    doc.header["$MEASUREMENT"] = 1
    msp = doc.modelspace()
    for name, color in (("SECTION_SURFACE", 7), ("SECTION_DIMENSION", 3), ("SECTION_LABEL", 5), ("SECTION_CENTER", 1)):
        doc.layers.new(name, dxfattribs={"color": color})
    for e in result["entities"]:
        attrs = {"layer": e["layer"]}
        if e["type"] == "line":
            msp.add_line(e["start"], e["end"], dxfattribs=attrs)
        elif e["type"] == "polyline":
            msp.add_lwpolyline(e["points"], close=e.get("closed", False), dxfattribs=attrs)
        elif e["type"] == "text":
            msp.add_text(e["text"], dxfattribs={**attrs, "insert": e["position"], "height": e["height"]})
        else:
            raise ValueError(f"不支持横断面实体类型：{e['type']}")
    payload = json.dumps(result["spec"], ensure_ascii=False, allow_nan=False)
    doc.rootdict.add_xrecord("PLANNINGWB_SECTIONSPEC").reset([(1, payload[i:i+200]) for i in range(0, len(payload), 200)])
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)


def get_example() -> dict:
    """Original teaching values, not derived dimensions from the asset library."""
    return {"schema_version": "1.0", "kind": "road_cross_section", "units": "m", "coordinate_reference": "local_cartesian",
            "synthetic": True, "source": "synthetic_teacher_assignment", "normative_status": "teaching_parameters",
            "reference_elevation": 100.0, "elevation_reference": "synthetic_local_datum",
            "slope_convention": "outward_rise_percent", "components": [
                {"id": "left-car", "name": "左侧车行部分", "side": "left", "order": 0, "role": "carriageway", "width": 7, "slope_percent": -2},
                {"id": "left-cycle", "name": "左侧骑行部分", "side": "left", "order": 1, "role": "cycleway", "width": 2, "slope_percent": -1.5},
                {"id": "left-walk", "name": "左侧步行部分", "side": "left", "order": 2, "role": "sidewalk", "width": 3, "slope_percent": -1},
                {"id": "right-car", "name": "右侧车行部分", "side": "right", "order": 0, "role": "carriageway", "width": 7, "slope_percent": -2},
                {"id": "right-green", "name": "右侧绿带", "side": "right", "order": 1, "role": "greenbelt", "width": 2, "slope_percent": -1.5},
                {"id": "right-walk", "name": "右侧步行部分", "side": "right", "order": 2, "role": "sidewalk", "width": 3, "slope_percent": -1}]}
