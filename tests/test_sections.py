import copy
import json

import ezdxf
import pytest

from app.sections import export_section_dxf, generate, get_example


def codes(result):
    return {e["code"] for e in result["report"]["errors"]}


def test_example_true_offsets_elevations_and_independent_copy():
    spec = get_example()
    before = copy.deepcopy(spec)
    result = generate(spec)
    assert not codes(result)
    assert result["metrics"]["total_width"] == 24
    assert result["metrics"]["endpoints"]["left"] == pytest.approx([-12, 99.8])
    assert result["metrics"]["endpoints"]["right"] == pytest.approx([12, 99.8])
    surface = [e for e in result["entities"] if e["layer"] == "SECTION_SURFACE"]
    assert len(surface) == 6
    assert surface[0]["start"] == [0, 100]
    assert surface[0]["end"] == pytest.approx([-7, 99.86])
    assert spec == before
    result["spec"]["components"][0]["width"] = 999
    assert spec == before


def test_positive_slope_rises_on_both_sides_and_order_is_semantic():
    source = get_example()
    source["components"] = [source["components"][3], source["components"][0]]
    for c in source["components"]:
        c["slope_percent"] = 2
    result = generate(source)
    assert not codes(result)
    assert result["metrics"]["endpoints"]["left"] == pytest.approx([-7, 100.14])
    assert result["metrics"]["endpoints"]["right"] == pytest.approx([7, 100.14])


@pytest.mark.parametrize("field,value,code", [("units", "mm", "units_required"), ("reference_elevation", None, "reference_elevation_required"),
    ("reference_elevation", float("nan"), "reference_elevation_required"), ("slope_convention", "global_dz_dx", "slope_convention_required")])
def test_invalid_section_input_has_no_geometry(field, value, code):
    source = get_example()
    source[field] = value
    result = generate(source)
    assert code in codes(result)
    assert not result["entities"]


@pytest.mark.parametrize("field,value,code", [("width", 0, "invalid_width"), ("width", True, "invalid_width"),
    ("slope_percent", None, "invalid_slope"), ("order", -1, "invalid_order"), ("side", "middle", "invalid_side"),
    ("role", "mystery", "invalid_role"), ("curb_height", .15, "unsupported_structure")])
def test_invalid_components_not_silently_defaulted(field, value, code):
    source = get_example()
    source["components"][0][field] = value
    result = generate(source)
    assert code in codes(result)
    assert not result["entities"]


def test_duplicate_order_is_rejected_and_left_width_changes_only_left_end():
    source = get_example()
    source["components"][1]["order"] = 0
    assert "invalid_order" in codes(generate(source))
    source = get_example()
    source["components"][0]["width"] = 9
    result = generate(source)
    assert result["metrics"]["endpoints"]["left"] == pytest.approx([-14, 99.76])
    assert result["metrics"]["endpoints"]["right"] == pytest.approx([12, 99.8])


def test_dxf_contains_same_real_surface_coordinates_units_and_metadata(tmp_path):
    result = generate(get_example())
    path = tmp_path / "section.dxf"
    export_section_dxf(result, path)
    doc = ezdxf.readfile(path)
    assert doc.units == 6
    lines = list(doc.modelspace().query('LINE[layer=="SECTION_SURFACE"]'))
    assert len(lines) == 6
    assert tuple(lines[0].dxf.end) == pytest.approx((-7, 99.86, 0))
    payload = "".join(tag.value for tag in doc.rootdict["PLANNINGWB_SECTIONSPEC"].tags if tag.code == 1)
    assert json.loads(payload) == result["spec"]
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        export_section_dxf(result, path)
    assert path.read_bytes() == before
    bad = generate({"kind": "road_cross_section"})
    with pytest.raises(ValueError):
        export_section_dxf(bad, tmp_path / "bad.dxf")


def test_longitudinal_entry_cannot_fabricate_terrain():
    result = generate({"kind": "road_longitudinal_section"})
    assert codes(result) == {"needs_input"}
    assert result["status"] == "needs_input"
    assert not result["entities"]


@pytest.mark.parametrize("narrow_width", [2, 0.25])
def test_actual_exported_label_boxes_fit_component_spans_without_center_alignment(tmp_path, narrow_width):
    from ezdxf import bbox
    source = get_example()
    source["components"][1]["width"] = narrow_width
    source["components"][1]["name"] = "左侧需要保留完整说明的很长骑行组成名称"
    result = generate(source)
    assert not codes(result)
    assert len(result["entities"]) == 39
    annotations = next(c for c in result["report"]["checks"] if c["code"] == "component_annotations")
    names = {c["component_id"]: c["full_name"] for c in annotations["components"]}
    assert names["left-cycle"] == source["components"][1]["name"]
    assert result["spec"]["components"][1]["name"] == names["left-cycle"]
    surface = {e["component_id"]: e for e in result["entities"] if e["layer"] == "SECTION_SURFACE"}
    out = tmp_path / "fitted-labels.dxf"
    export_section_dxf(result, out)
    doc = ezdxf.readfile(out)
    exported_text = iter(doc.modelspace().query("TEXT"))
    boxes = {"component_width": [], "component_slope": []}
    for source_text in (e for e in result["entities"] if e["type"] == "text"):
        cad_text = next(exported_text)
        if "component_id" not in source_text:
            continue
        assert cad_text.dxf.halign == 0  # Native default LEFT, not a hidden centred-text dependency.
        measured = bbox.extents([cad_text])
        line = surface[source_text["component_id"]]
        x0, x1 = sorted((line["start"][0], line["end"][0]))
        assert x0 <= measured.extmin.x < measured.extmax.x <= x1
        boxes[source_text["annotation_kind"]].append(measured)
    # Adjacent label boxes must remain disjoint, including the two centre labels.
    for row in boxes.values():
        row.sort(key=lambda b: b.extmin.x)
        assert all(a.extmax.x < b.extmin.x for a, b in zip(row, row[1:]))
    cycle_text = next(e for e in result["entities"] if e.get("component_id") == "left-cycle" and e.get("annotation_kind") == "component_width")
    assert cycle_text["text"] == f"骑行{narrow_width:g}m"
    if narrow_width < 1:
        assert cycle_text["height"] < 0.1  # Narrow parts shrink; no fixed minimum causes overflow.
