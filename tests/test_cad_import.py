"""Pure import acceptance, including a sanitized real CAD selection recording.

Recorded geometry below is from selected_read in the successful local evidence
cad-inspect-20261012-214526.json. Document identity is replaced and unrelated
document metadata/paths are deliberately excluded. Bulge fixtures are synthetic
unit tests; they are not claimed as newly recorded CAD operations.
"""
import copy
import math

import pytest

from app.cad_import import CadImportError, from_inspection
from app.geometry import generate


@pytest.fixture
def recorded_selection():
    return {
        "connected": True,
        "document": {"identity": "acad-sanitized-selection-recording", "document_id": None, "units": 6},
        "truncated": False, "layers_truncated": False,
        "active_document_unchanged_during_read": True,
        "selection": {"source": "PickfirstSelectionSet", "count": 2, "truncated": False,
                      "entities": [
                          {"handle": "80", "object_name": "AcDbLine", "layer": "PW_READ_TEST",
                           "type": "line", "start": [0.0, 0.0, 0.0], "end": [50.0, 0.0, 0.0],
                           "coordinate_system": "WCS", "is_2d_planar": True, "length": 50.0},
                          {"handle": "81", "object_name": "AcDbArc", "layer": "PW_READ_TEST",
                           "type": "arc", "center": [50.0, 10.0, 0.0], "normal": [0.0, 0.0, 1.0],
                           "radius": 10.0, "start_angle": 4.71238898038469, "end_angle": 0.0,
                           "start_point": [50.0, 0.0, 0.0], "end_point": [60.0, 10.0, 0.0],
                           "arc_length": 15.707963267948966, "angle_units": "radians_ccw",
                           "coordinate_system": "center/endpoints=WCS; angles=entity OCS",
                           "is_2d_planar": True}]}}


def convert(snapshot):
    return from_inspection(snapshot, confirmed_centerlines=True)


def with_polyline(snapshot, bulge=0.0):
    entity = {"handle": "A1", "object_name": "AcDbPolyline", "layer": "CENTERLINE",
              "type": "polyline", "points": [[0.0, 0.0], [10.0, 0.0]],
              "bulges": [bulge, 0.0], "elevation": 0.0, "normal": [0.0, 0.0, 1.0],
              "closed": False, "is_2d_planar": True, "coordinate_system": "OCS"}
    snapshot["selection"].update(count=1, entities=[entity])
    return entity


def test_recorded_real_selection_preserves_geometry_provenance_and_no_design_guesses(recorded_selection):
    before = copy.deepcopy(recorded_selection)
    result = convert(recorded_selection)
    spec, source = result["spec"], result["source"]
    assert result["synthetic"] is False
    assert spec["units"] == "m"
    assert all(spec[field] is None for field in
               ("left_width", "right_width", "junction_radius", "qa_tolerance", "coordinate_reference"))
    assert spec["roads"][0]["segments"] == [{"type": "line", "start": [0, 0], "end": [50, 0]}]
    arc = spec["roads"][1]["segments"][0]
    assert arc["center"] == [50, 10] and arc["radius"] == 10
    assert (arc["end_angle"] - arc["start_angle"]) % math.tau == pytest.approx(math.pi / 2)
    assert source["handles"] == ["80", "81"]
    assert source["document_identity"] == before["document"]["identity"]
    assert all(r["junction_type"] is None and r["left_width"] is None for r in spec["roads"])
    assert source["writes_performed"] is False and source["coordinates_scaled"] is False
    assert recorded_selection == before and result == convert(before)
    codes = {e["code"] for e in generate(spec)["report"]["errors"]}
    assert {"coordinate_reference_required", "invalid_width", "invalid_junction_radius", "invalid_tolerance"} <= codes


@pytest.mark.parametrize("confirmation", [False, None, 1, "true"])
def test_requires_explicit_boolean_confirmation(recorded_selection, confirmation):
    with pytest.raises(CadImportError) as error:
        from_inspection(recorded_selection, confirmed_centerlines=confirmation)
    assert error.value.code == "centerline_confirmation_required"


@pytest.mark.parametrize("code,unit", [(6, "m"), (4, "mm"), (5, "cm"), (2, "ft"), (1, "in"),
                                    (0, None), (7, None), (None, None), (True, None)])
def test_units_retained_without_rescaling(recorded_selection, code, unit):
    recorded_selection["document"]["units"] = code
    result = convert(recorded_selection)
    assert result["spec"]["units"] == unit
    assert result["spec"]["roads"][0]["segments"][0]["end"] == [50, 0]
    assert ("units" in result["spec"]["_import"]["required_fields"]) == (unit is None)


@pytest.mark.parametrize("field,value,code", [("connected", False, "cad_not_connected"),
    ("active_document_unchanged_during_read", False, "document_changed"),
    ("truncated", True, "truncated_snapshot"), ("layers_truncated", True, "truncated_snapshot")])
def test_rejects_incomplete_or_switched_snapshot(recorded_selection, field, value, code):
    recorded_selection[field] = value
    with pytest.raises(CadImportError) as error:
        convert(recorded_selection)
    assert error.value.code == code


@pytest.mark.parametrize("field,value,code", [("truncated", True, "truncated_snapshot"),
    ("count", 0, "invalid_selection_count"), ("count", 1, "invalid_selection_count"),
    ("source", "ModelSpace", "invalid_selection_source")])
def test_selection_must_be_complete_nonempty_pickfirst(recorded_selection, field, value, code):
    recorded_selection["selection"][field] = value
    with pytest.raises(CadImportError) as error:
        convert(recorded_selection)
    assert error.value.code == code


def test_no_fallback_to_whole_drawing_and_no_import_of_unselected_objects(recorded_selection):
    recorded_selection["entities"] = [{"type": "unsupported", "object_name": "AcDbText"}]
    assert len(convert(recorded_selection)["spec"]["roads"]) == 2
    recorded_selection["selection"].update(count=0, entities=[])
    with pytest.raises(CadImportError, match="非空"):
        convert(recorded_selection)


def test_selected_text_rejects_entire_batch(recorded_selection):
    recorded_selection["selection"]["entities"].append({"handle": "82", "type": "unsupported", "object_name": "AcDbText"})
    recorded_selection["selection"]["count"] = 3
    with pytest.raises(CadImportError) as error:
        convert(recorded_selection)
    assert error.value.code == "unsupported_selection"


def test_never_trusts_planarity_flag_over_actual_geometry(recorded_selection):
    recorded_selection["selection"]["entities"][0]["end"][2] = 5
    with pytest.raises(CadImportError) as error:
        convert(recorded_selection)
    assert error.value.code == "nonplanar_geometry"


@pytest.mark.parametrize("normal", [[0, 0, -1], [0, 1, 0]])
def test_tilted_or_reversed_ocs_rejected(recorded_selection, normal):
    recorded_selection["selection"]["entities"][1]["normal"] = normal
    with pytest.raises(CadImportError) as error:
        convert(recorded_selection)
    assert error.value.code == "nonplanar_geometry"


def test_inconsistent_arc_and_nonfinite_data_rejected(recorded_selection):
    arc = recorded_selection["selection"]["entities"][1]
    arc["end_point"][0] = 61
    with pytest.raises(CadImportError) as error:
        convert(recorded_selection)
    assert error.value.code == "inconsistent_geometry"
    arc["end_point"][0] = 60
    arc["radius"] = math.nan
    with pytest.raises(CadImportError) as error:
        convert(recorded_selection)
    assert error.value.code == "invalid_geometry"


@pytest.mark.parametrize("bulge", [-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0])
def test_bulge_keeps_orientation_endpoints_and_major_arcs(recorded_selection, bulge):
    with_polyline(recorded_selection, bulge)
    segment = convert(recorded_selection)["spec"]["roads"][0]["segments"][0]
    if bulge == 0:
        assert segment == {"type": "line", "start": [0, 0], "end": [10, 0]}
        return
    assert segment["type"] == "arc" and segment["clockwise"] is (bulge < 0)
    for angle, point in ((segment["start_angle"], [0, 0]), (segment["end_angle"], [10, 0])):
        actual = [segment["center"][0] + segment["radius"] * math.cos(angle),
                  segment["center"][1] + segment["radius"] * math.sin(angle)]
        assert actual == pytest.approx(point, abs=1e-9)
    sweep = ((segment["start_angle"] - segment["end_angle"]) if bulge < 0
             else (segment["end_angle"] - segment["start_angle"])) % math.tau
    assert sweep == pytest.approx(4 * math.atan(abs(bulge)))


@pytest.mark.parametrize("change", ["closed", "coincident_ends", "elevated", "incomplete_bulges"])
def test_polygon_elevation_and_incomplete_polyline_rejected(recorded_selection, change):
    entity = with_polyline(recorded_selection)
    if change == "closed":
        entity["closed"] = True
    elif change == "coincident_ends":
        entity["points"][1] = [0, 0]
    elif change == "elevated":
        entity["elevation"] = 3
    else:
        entity["bulges"] = [0]
    with pytest.raises(CadImportError):
        convert(recorded_selection)


def test_duplicate_handles_and_overlarge_selections_rejected(recorded_selection):
    recorded_selection["selection"]["entities"][1]["handle"] = "80"
    with pytest.raises(CadImportError) as error:
        convert(recorded_selection)
    assert error.value.code == "duplicate_handle"
    recorded_selection["selection"].update(count=201, entities=[{}] * 201)
    with pytest.raises(CadImportError) as error:
        convert(recorded_selection)
    assert error.value.code == "invalid_selection_count"


def test_single_imported_line_generates_only_after_design_fields_completed(recorded_selection):
    recorded_selection["selection"]["entities"].pop()
    recorded_selection["selection"]["count"] = 1
    spec = convert(recorded_selection)["spec"]
    spec.update(coordinate_reference="local_cartesian", left_width=5, right_width=5,
                junction_radius=0, qa_tolerance=0.01)
    spec["roads"][0].update(left_width=5, right_width=5, junction_type="at_grade")
    result = generate(spec)
    assert result["report"]["errors"] == []
    assert result["metrics"]["total_centerline_length"] == 50


def test_mixed_polyline_retains_geometry_and_explains_generator_limit(recorded_selection):
    entity = with_polyline(recorded_selection, 0.5)
    entity["points"].append([20, 0])
    entity["bulges"].append(0)
    result = convert(recorded_selection)
    assert [s["type"] for s in result["spec"]["roads"][0]["segments"]] == ["arc", "line"]
    assert any("复合线形" in w for w in result["spec"]["_import"]["warnings"])
