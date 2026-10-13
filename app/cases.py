"""Synthetic, explicitly labelled teaching cases for the local workbench."""
from __future__ import annotations

import copy
import math


def _line(road_id, name, start, end, width=None):
    road = {"id": road_id, "name": name, "level": 0, "direction": "segment_order", "station_start": 0, "junction_type": "at_grade",
            "segments": [{"type": "line", "start": start, "end": end}]}
    if width is not None:
        road.update(left_width=width, right_width=width)
    return road


def _rectangle(x0, y0, x1, y1):
    return {"type": "polyline", "layer": "CONTEXT", "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "closed": True}


def _base():
    return {"schema_version": "1.0", "width_semantics": "road_boundary", "normative_status": "teaching_parameters",
            "synthetic": True, "source": "synthetic_teacher_assignment", "units": "m", "coordinate_reference": "local_cartesian", "left_width": 8,
            "right_width": 8, "junction_radius": 4, "qa_tolerance": 0.005,
            "roads": [], "constraints": [], "context_entities": []}


def _regulatory():
    spec = _base()
    spec["roads"] = [
        _line("east-west", "东西向主路", [-120, 0], [160, 0]),
        _line("north-south", "南北向道路", [0, -80], [0, 80]),
        _line("branch", "北侧支路", [80, 0], [80, 75], 6),
    ]
    spec["context_entities"] = [
        _rectangle(-90, 22, -32, 57), _rectangle(23, 22, 54, 57),
        _rectangle(99, 24, 143, 55), _rectangle(-89, -58, -25, -22),
        {"type": "text", "position": [-110, 86], "text": "合成教学案例：正交道路平面", "height": 3},
    ]
    oblique = copy.deepcopy(spec)
    oblique['roads'][1]['segments'][0].update(start=[-40, -40*math.sqrt(3)], end=[40, 40*math.sqrt(3)])
    oblique['roads'][1]['name'] = '60度斜交道路'
    oblique['context_entities'] = [{'type':'text','position':[-110,86], 'text':'合成教学：60度斜交 X 口与正交 T 口','height':3}]
    tee = copy.deepcopy(oblique)
    tee['roads'] = [copy.deepcopy(spec['roads'][0]), _line('oblique-branch','60度接入支路',[0,0],[60,60*math.sqrt(3)])]
    tee['context_entities'][0]['text'] = '合成教学：60度斜交 T 口'
    return {"id": "regulatory-road-plan", "name": "控规道路平面：X / T 路口",
            "description": "以三条合成中心线生成道路边界、一个十字路口与一个丁字路口，研究左右宽度和真实圆角。",
            "synthetic": True, "units": "m", "difficulty": "基础",
            "objectives": ["区分中心线、左右宽度与总宽", "检查 X/T 路口边线裁剪及圆弧相切", "理解单位与图层并导出可编辑 DXF"],
            "steps": ["确认本案例为局部坐标、单位米的合成数据。", "生成并检查 2 个路口；识别中心线、边线、转角和端头图层。",
                      "把 junction_radius 从 4 改为 6，比较转角而不是把它当作规范推荐值。",
                      "修改支路左右宽度，重新校核边线和路口。", "导出 DXF 后在 CAD 中检查 ARC / LWPOLYLINE 及单位。"],
            "expected": {"road_count": 3, "junction_count": 2, "errors": 0, "total_centerline_length": 515},
            "limitations": ["参数为教学假设，不代表任何城市道路规范。", "不包含道路自动选线、交通评估或施工设计。"],
            "spec": spec, "default_variant": "orthogonal",
            "variants": [{"id":"orthogonal","name":"正交基线：X / T 路口","spec":copy.deepcopy(spec)},
                         {"id":"oblique-x60","name":"60°斜交 X 口 + 正交 T 口","spec":oblique},
                         {"id":"oblique-t60","name":"60°斜交 T 口","spec":tee}]}


def _renewal():
    base = _base()
    base.update(left_width=6, right_width=6, junction_radius=3)
    base["constraints"] = [{"id": "retained-building", "name": "保留建筑", "type": "preserve", "source": "synthetic_teacher_assignment", "status": "retained",
                            "polygon": [[-15, -4], [15, -4], [15, 16], [-15, 16]]}]
    base["context_entities"] = [_rectangle(38, 12, 76, 35), _rectangle(-48, 20, -27, 43),
                                {"type": "text", "position": [-13, 5], "text": "保留建筑", "height": 2},
                                {"type": "text", "position": [-65, 70], "text": "合成更新案例：保留建筑与支路微调", "height": 3}]
    boundary = [[-100, -80], [125, -80], [125, 90], [-100, 90]]
    base["boundary"] = {"polygon": boundary, "source": "synthetic_teacher_assignment", "semantics": "study_area_only"}
    base["context_entities"].extend([
        {"type": "polyline", "layer": "BLOCK_BOUNDARY", "points": boundary, "closed": True},
        {"type": "line", "layer": "EXISTING_ROAD", "start": [-65, 0], "end": [100, 0], "source": "synthetic_teacher_assignment"},
        {"type": "line", "layer": "EXISTING_ROAD", "start": [-65, 6], "end": [100, 6]},
        {"type": "line", "layer": "EXISTING_ROAD", "start": [-65, -6], "end": [100, -6]}])
    a, b = copy.deepcopy(base), copy.deepcopy(base)
    for spec, y in ((a, 0), (b, -20)):
        spec["roads"] = [_line("avenue", "既有道路（保留）", [-65, -60], [-65, 60], 8),
                         _line("renewal-branch", "更新支路", [-65, y], [100, y])]
        spec["roads"][0]["status"] = "retained"
        spec["roads"][1]["status"] = "proposed"
    return {"id": "renewal-street-adjustment", "name": "城市更新：保留建筑下的支路 A/B",
            "description": "对比穿入保留建筑的方案 A 与南移 20 米的方案 B，用实际碰撞校核解释方案调整。",
            "synthetic": True, "units": "m", "difficulty": "比较",
            "objectives": ["把建筑保留要求表示为可校核多边形约束", "定位方案 A 的侵入并阻止错误成果导出", "比较 B 的净距、道路长度与编辑记录"],
            "steps": ["先选择方案 A，生成后查看 constraint_conflict 和保留建筑。",
                      "确认冲突来自道路边界而非仅中心线。", "选择方案 B，支路南移 20 米；重新生成并查看最小净距。",
                      "对比方案并记录取舍；本案例没有证明 20 米是规划最优值。", "仅导出校核无 errors 的 B；继续在 CAD 中检查。"],
            "expected": {"default_variant": "B", "A": {"errors": ["constraint_conflict"]}, "B": {"errors": 0, "constraint_clearance": 10}},
            "limitations": ["两个方案均为原创合成教学样例，不代表真实地块。", "未考虑产权、消防、交通影响及地下管线；工程决策需追加真实约束。"],
            "spec": b, "default_variant": "B",
            "variants": [{"id": "A", "name": "A：原支路，与保留建筑冲突", "spec": a},
                         {"id": "B", "name": "B：支路南移 20 m，避让建筑", "spec": b}]}


def _cross_section():
    from app.sections import get_example
    return {"id": "road-cross-section", "name": "道路横断面：明确组成、宽度与横坡", "synthetic": True,
            "description": "以明确的教学参数生成连续路表、宽度标注和中心高程；不生成结构层或纵断面。",
            "units": "m", "difficulty": "基础", "objectives": ["区分偏距、高程与道路平面坐标", "理解两侧向外横坡符号", "检查宽度与高程逐段累加"],
            "steps": ["确认基准高程100米为合成局部基准。", "检查每侧从中心向外的顺序、宽度和横坡。", "生成并核验总宽24米、两外端99.8米。", "改一个组成宽度后重新检查外端高程，导出1:1真实坐标DXF。"],
            "limitations": ["教学输入不代表规范推荐值。", "无地形、台阶、缘石、结构层、排水和纵断面设计。"],
            "expected": {"total_width": 24, "component_count": 6, "outer_elevation": 99.8}, "spec": get_example(), "variants": []}


def list_cases() -> list[dict]:
    return [{**{k: copy.deepcopy(v) for k, v in case.items() if k not in ("spec", "variants")},
             'available_variants':[{'id':v['id'],'name':v['name']} for v in case.get('variants',[])]}
            for case in (_regulatory(), _renewal(), _cross_section(), _parcels())]


def get_case(case_id: str) -> dict:
    for case in (_regulatory(), _renewal(), _cross_section(), _parcels()):
        if case["id"] == case_id:
            return copy.deepcopy(case)
    raise KeyError(f"未知案例：{case_id}")


def _parcels():
    from .parcels import get_example
    return {'id':'regulatory-parcels','name':'控规地块：道路扣除、指标与图则','synthetic':True,
            'description':'原创240×180米合成边界，保留孔洞，计算道路并集、净地块面积和控制指标。',
            'units':'m','difficulty':'地块与图则','spec':get_example(),'variants':[],
            'objectives':['道路与地块面积守恒','唯一地块编号与指标表同步','独立图则和可编辑CAD实体'],
            'steps':['在地块与图则页面查看合成参数。','修改道路总宽并重算地块。','明确输入指标，未给指标保持待核。','生成总图、CSV和逐块图则。'],
            'limitations':['不自动推断法定用地分类或控制指标。','道路用地缓冲不是交叉口工程设计。','无完整规划合规结论。']}
