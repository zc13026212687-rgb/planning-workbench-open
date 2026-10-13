import copy
import math

import ezdxf
import pytest

from app.cases import get_case, list_cases
from app.geometry import export_dxf, generate, import_dxf


def spec(roads=None):
    return {"units": "m", "coordinate_reference": "local_cartesian", "left_width": 8,
            "right_width": 8, "junction_radius": 4, "qa_tolerance": 0.001,
            "roads": roads or [{"id": "r", "segments": [{"type": "line", "start": [0, 0], "end": [100, 0]}]}],
            "constraints": [], "context_entities": []}


def codes(result):
    return [e["code"] for e in result["report"]["errors"]]


def test_straight_asymmetric_offsets_area_and_input_immutability():
    source = spec()
    source.update(left_width=5, right_width=9)
    before = copy.deepcopy(source)
    result = generate(source)
    assert not codes(result)
    edges = [e for e in result["entities"] if e["layer"] == "ROAD_EDGE"]
    assert {e["start"][1] for e in edges} == {5, -9}
    assert result["metrics"]["road_area"] == pytest.approx(1400)
    assert source == before


def test_true_arc_concentric_offsets_and_sector_area():
    source = spec([{"id": "curve", "segments": [{"type": "arc", "center": [0, 0], "radius": 50,
                  "start_angle": 0, "end_angle": math.pi / 2}]}])
    result = generate(source)
    assert not codes(result)
    assert sorted(e["radius"] for e in result["entities"] if e["type"] == "arc") == [42, 50, 58]
    assert result["metrics"]["total_centerline_length"] == pytest.approx(25 * math.pi, abs=1e-6)
    expected = math.pi / 4 * (58**2 - 42**2)
    assert result["metrics"]["road_area"] == pytest.approx(expected, abs=0.05)


def test_clockwise_arc_preserves_left_right_meaning():
    source = spec([{"id": "cw", "left_width": 3, "right_width": 7,
                    "segments": [{"type": "arc", "center": [0, 0], "radius": 40,
                                  "start_angle": math.pi / 2, "end_angle": 0, "clockwise": True}]}])
    result = generate(source)
    assert not codes(result)
    assert sorted(e["radius"] for e in result["entities"] if e["layer"] == "ROAD_EDGE") == [33, 43]


def test_x_junction_has_four_true_tangent_fillets_and_correct_area():
    source = spec([{"id": "ew", "segments": [{"type": "line", "start": [-100, 0], "end": [100, 0]}]},
                   {"id": "ns", "segments": [{"type": "line", "start": [0, -60], "end": [0, 60]}]}])
    result = generate(source)
    assert not codes(result)
    fillets = [e for e in result["entities"] if e["layer"] == "ROAD_JUNCTION"]
    assert len(fillets) == 4
    assert {tuple(round(v, 6) for v in e["center"]) for e in fillets} == {(12, 12), (-12, 12), (-12, -12), (12, -12)}
    edges = [e for e in result["entities"] if e["layer"] == "ROAD_EDGE"]
    for arc in fillets:
        assert arc["radius"] == 4
        for angle in (arc["start_angle"], arc["end_angle"]):
            p = [arc["center"][0] + 4 * math.cos(angle), arc["center"][1] + 4 * math.sin(angle)]
            incident = [e for e in edges if min(math.dist(p, e["start"]), math.dist(p, e["end"])) < 1e-6]
            assert len(incident) == 1
            v = [incident[0]["end"][i] - incident[0]["start"][i] for i in (0, 1)]
            radial = [p[i] - arc["center"][i] for i in (0, 1)]
            assert abs(sum(v[i] * radial[i] for i in (0, 1))) < 1e-6
    expected = 200 * 16 + 120 * 16 - 16 * 16 + 4 * (16 - math.pi * 16 / 4)
    assert result["metrics"]["road_area"] == pytest.approx(expected, abs=0.04)


def test_cases_t_x_counts_and_renewal_constraint_variants():
    assert len(list_cases()) == 4
    regulatory = generate(get_case("regulatory-road-plan")["spec"])
    assert not codes(regulatory)
    assert regulatory["metrics"]["junction_count"] == 2
    assert regulatory["metrics"]["total_centerline_length"] == 515
    assert len(regulatory["entities"]) == 34
    renewal = get_case("renewal-street-adjustment")
    a, b = [generate(v["spec"]) for v in renewal["variants"]]
    assert "constraint_conflict" in codes(a)
    assert not codes(b)
    check = next(e for e in b["report"]["checks"] if e["code"] == "constraint_clear")
    assert check["clearance"] == pytest.approx(10)


@pytest.mark.parametrize("field,value,code", [("units", None, "units_required"),
    ("left_width", -2, "invalid_width"), ("right_width", float("nan"), "invalid_width"),
    ("junction_radius", -1, "invalid_junction_radius"), ("qa_tolerance", 0, "invalid_tolerance")])
def test_bad_numeric_inputs_are_visible(field, value, code):
    source = spec()
    source[field] = value
    assert code in codes(generate(source))


def test_zero_line_inner_radius_and_short_junction_rejected():
    zero = spec()
    zero["roads"][0]["segments"][0]["end"] = [0, 0]
    assert "zero_length" in codes(generate(zero))
    curve = spec([{"id": "a", "segments": [{"type": "arc", "center": [0, 0], "radius": 5, "start_angle": 0, "end_angle": 1}]}])
    assert "inner_radius_nonpositive" in codes(generate(curve))
    roads = [{"id": "a", "segments": [{"type": "line", "start": [-10, 0], "end": [10, 0]}]},
             {"id": "b", "segments": [{"type": "line", "start": [-10, -10], "end": [10, 10]}]}]
    assert "insufficient_junction_space" in codes(generate(spec(roads)))
    roads[1]["segments"][0].update(start=[0, -10], end=[0, 10])
    assert "insufficient_junction_space" in codes(generate(spec(roads)))


def test_dxf_roundtrip_has_units_bulge_arc_and_uses_actual_cad_edits(tmp_path):
    source = spec([{"id": "curve", "segments": [{"type": "arc", "center": [0, 0], "radius": 50,
                   "start_angle": 0, "end_angle": math.pi / 2}]}])
    target = tmp_path / "curve.dxf"
    export_dxf(generate(source), target)
    doc = ezdxf.readfile(target)
    assert doc.units == 6
    centers = list(doc.modelspace().query('LWPOLYLINE[layer=="ROAD_CENTER"]'))
    assert len(centers) == 1
    assert list(centers[0].get_points("xyb"))[0][2] == pytest.approx(math.tan(math.pi / 8))
    assert len(list(doc.modelspace().query("ARC"))) == 2
    imported = import_dxf(target)
    s = imported["roads"][0]["segments"][0]
    assert s["radius"] == pytest.approx(50)
    assert s["center"] == pytest.approx([0, 0])
    assert not codes(generate(imported))
    # Modify the actual CAD centerline while leaving the embedded spec intact.
    centers[0].translate(10, 20, 0)
    doc.saveas(target)
    moved = import_dxf(target)["roads"][0]["segments"][0]
    assert moved["center"] == pytest.approx([10, 20])


def test_external_dxf_requires_units_widths_and_preserves_negative_bulge(tmp_path):
    doc = ezdxf.new("R2013")
    doc.units = 0
    doc.modelspace().add_lwpolyline([(0, 10, -math.tan(math.pi / 8)), (10, 0, 0)], format="xyb")
    target = tmp_path / "external.dxf"
    doc.saveas(target)
    imported = import_dxf(target)
    assert imported["units"] is None
    assert imported["left_width"] is None
    arc = imported["roads"][0]["segments"][0]
    assert arc["clockwise"] is True
    assert arc["radius"] == pytest.approx(10)
    assert arc["center"] == pytest.approx([0, 0])
    assert {"units_required", "invalid_width"}.issubset(codes(generate(imported)))


def test_invalid_result_cannot_export_and_existing_file_not_overwritten(tmp_path):
    invalid = generate(get_case("renewal-street-adjustment")["variants"][0]["spec"])
    with pytest.raises(ValueError):
        export_dxf(invalid, tmp_path / "bad.dxf")
    result = generate(spec())
    target = tmp_path / "good.dxf"
    export_dxf(result, target)
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        export_dxf(result, target)
    assert target.read_bytes() == before


def test_per_road_widths_do_not_require_global_widths():
    source = spec()
    del source["left_width"]
    del source["right_width"]
    source["roads"][0].update(left_width=3, right_width=5)
    result = generate(source)
    assert not codes(result)
    assert result["metrics"]["road_area"] == 800


def test_rotated_and_translated_x_keeps_analytic_area():
    source = spec([{"id": "ew", "segments": [{"type": "line", "start": [-100, 0], "end": [100, 0]}]},
                   {"id": "ns", "segments": [{"type": "line", "start": [0, -60], "end": [0, 60]}]}])
    original = generate(source)
    angle = 0.317
    for road in source["roads"]:
        for key in ("start", "end"):
            x, y = road["segments"][0][key]
            road["segments"][0][key] = [10000 + x * math.cos(angle) - y * math.sin(angle),
                                        20000 + x * math.sin(angle) + y * math.cos(angle)]
    rotated = generate(source)
    assert not codes(rotated)
    assert rotated["metrics"]["road_area"] == pytest.approx(original["metrics"]["road_area"], abs=0.001)


def test_near_miss_corridor_overlap_and_duplicate_centerline_rejected():
    parallel = spec([{"id": "a", "segments": [{"type": "line", "start": [0, 0], "end": [100, 0]}]},
                     {"id": "b", "segments": [{"type": "line", "start": [0, 10], "end": [100, 10]}]}])
    assert "unconnected_corridor_overlap" in codes(generate(parallel))
    parallel["roads"][1]["segments"][0].update(start=[0, 0], end=[100, 0])
    assert "overlapping_centerlines" in codes(generate(parallel))


def test_grade_levels_are_connectivity_not_fake_elevation(tmp_path):
    source = spec([{"id": "ew", "level": 0, "segments": [{"type": "line", "start": [-100, 0], "end": [100, 0]}]},
                   {"id": "ns", "level": 1, "segments": [{"type": "line", "start": [0, -60], "end": [0, 60]}]}])
    result = generate(source)
    assert not codes(result)
    assert result["metrics"]["junction_count"] == 0
    assert result["metrics"]["road_area"] == 5120
    assert any(e["code"] == "logical_levels_only" for e in result["report"]["warnings"])
    target = tmp_path / "levels.dxf"
    export_dxf(result, target)
    centers = ezdxf.readfile(target).modelspace().query('LWPOLYLINE[layer=="ROAD_CENTER"]')
    assert all(e.dxf.elevation == 0 for e in centers)
    assert {r["level"] for r in import_dxf(target)["roads"]} == {0, 1}


def test_dxf_3d_is_rejected_instead_of_silently_flattened(tmp_path):
    doc = ezdxf.new("R2013")
    doc.modelspace().add_line((0, 0, 5), (100, 0, 10))
    target = tmp_path / "elevated.dxf"
    doc.saveas(target)
    with pytest.raises(ValueError, match="高程"):
        import_dxf(target)


def test_arc_intersection_and_unsupported_bend_are_visible():
    source = spec([{"id": "arc", "segments": [{"type": "arc", "center": [0, 0], "radius": 50,
                    "start_angle": 0, "end_angle": math.pi / 2}]},
                   {"id": "line", "segments": [{"type": "line", "start": [0, 25], "end": [100, 25]}]}])
    assert "unsupported_arc_junction" in codes(generate(source))
    bend = spec([{"id": "bend", "segments": [{"type": "line", "start": [0, 0], "end": [100, 0]},
                                               {"type": "line", "start": [100, 0], "end": [100, 100]}]}])
    assert "unsupported_node" in codes(generate(bend))


def test_constraint_self_intersection_is_not_repaired_or_silenced():
    source = spec()
    source["constraints"] = [{"id": "bad", "type": "preserve", "polygon": [[0, 0], [20, 20], [20, 0], [0, 20]]}]
    assert "invalid_constraint_polygon" in codes(generate(source))


def test_unknown_junction_needs_confirmation_but_separate_levels_do_not_connect():
    source = get_case("regulatory-road-plan")["spec"]
    source["roads"][1]["junction_type"] = "unknown"
    result = generate(source)
    assert "needs_confirmation" in codes(result)
    assert not result["entities"]
    source["roads"][1]["level"] = 1
    result = generate(source)
    assert not codes(result)
    assert result["metrics"]["junction_count"] == 1


def test_zero_radius_is_sharp_and_does_not_invent_fillet():
    source = get_case("regulatory-road-plan")["spec"]
    source["junction_radius"] = 0
    result = generate(source)
    assert not codes(result)
    assert not [e for e in result["entities"] if e["layer"] == "ROAD_JUNCTION"]
    assert result["metrics"]["junction_count"] == 2


def test_units_do_not_silently_scale_geometry_and_explicit_scaling_is_consistent(tmp_path):
    source = spec()
    original = generate(source)
    source["units"] = "mm"
    unchanged = generate(source)
    assert unchanged["metrics"]["road_area"] == original["metrics"]["road_area"]
    for key in ("left_width", "right_width", "junction_radius", "qa_tolerance"):
        source[key] *= 1000
    source["roads"][0]["segments"][0]["end"][0] *= 1000
    scaled = generate(source)
    assert not codes(scaled)
    assert scaled["metrics"]["road_area"] == original["metrics"]["road_area"] * 1e6
    out = tmp_path / "millimetres.dxf"
    export_dxf(scaled, out)
    assert ezdxf.readfile(out).units == 4
    assert import_dxf(out)["roads"][0]["segments"][0]["end"] == [100000, 0]


def test_clockwise_roundtrip_keeps_negative_bulge_and_left_right_widths(tmp_path):
    source = spec([{"id": "cw", "left_width": 3, "right_width": 7, "segments": [{"type": "arc", "center": [20, 30],
        "radius": 40, "start_angle": math.pi / 2, "end_angle": 0, "clockwise": True}]}])
    target = tmp_path / "cw.dxf"
    export_dxf(generate(source), target)
    center = next(iter(ezdxf.readfile(target).modelspace().query('LWPOLYLINE[layer=="ROAD_CENTER"]')))
    assert list(center.get_points("xyb"))[0][2] == pytest.approx(-math.tan(math.pi / 8))
    recovered = import_dxf(target)
    assert recovered["roads"][0]["segments"][0]["clockwise"]
    assert recovered["roads"][0]["left_width"] == 3
    assert recovered["roads"][0]["right_width"] == 7
    assert not codes(generate(recovered))


def test_disconnected_segments_and_abrupt_width_transition_rejected():
    source = spec([{"id": "r", "segments": [{"type": "line", "start": [0, 0], "end": [50, 0]},
                                               {"type": "line", "start": [60, 0], "end": [100, 0]}]}])
    assert "disconnected_alignment" in codes(generate(source))
    source["roads"] = [{"id": "a", "segments": [{"type": "line", "start": [0, 0], "end": [50, 0]}]},
                       {"id": "b", "left_width": 5, "right_width": 5, "segments": [{"type": "line", "start": [50, 0], "end": [100, 0]}]}]
    assert "unsupported_width_transition" in codes(generate(source))


def test_renewal_layers_variants_are_isolated_and_dxf_recovery_keeps_semantics(tmp_path):
    case = get_case("renewal-street-adjustment")
    baseline = get_case("renewal-street-adjustment")
    a, b = [v["spec"] for v in case["variants"]]
    a["roads"][1]["segments"][0]["start"][1] = 999
    assert b == baseline["variants"][1]["spec"]
    assert get_case("renewal-street-adjustment") == baseline
    result = generate(b)
    layers = {e["layer"] for e in result["entities"]}
    assert {"EXISTING_ROAD", "BLOCK_BOUNDARY", "RETAINED_OBJECT", "PROPOSED_ROAD_EDGE", "RETAINED_ROAD_EDGE"} <= layers
    assert b["width_semantics"] == "road_boundary"
    target = tmp_path / "renewal.dxf"
    export_dxf(result, target)
    recovered = import_dxf(target)
    assert recovered["boundary"] == b["boundary"]
    assert recovered["roads"][1]["status"] == "proposed"
    assert recovered["roads"][1]["junction_type"] == "at_grade"
    check = next(c for c in generate(recovered)["report"]["checks"] if c["code"] == "constraint_clear")
    assert check["clearance"] == 10

