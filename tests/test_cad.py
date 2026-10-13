import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.cad import CadBridge, CadError, validate_entities, _editable_xy_entities


def line(**changes):
    return {"id": "a", "type": "line", "layer": "PW_ROAD", "start": [0, 0], "end": [20, 0], **changes}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "5"])
def test_non_numeric_or_nonfinite_geometry_is_rejected_before_com(value):
    with pytest.raises(CadError):
        validate_entities([line(end=[value, 1])])


def test_duplicate_ids_and_zero_length_are_rejected():
    with pytest.raises(CadError, match="unique"):
        validate_entities([line(), line()])
    with pytest.raises(CadError, match="Zero-length"):
        validate_entities([line(end=[0, 0])])


def test_cad_layer_control_characters_are_rejected():
    with pytest.raises(CadError, match="layer"):
        validate_entities([line(layer="road\n_.ERASE")])


def test_arc_is_radians_and_keeps_ccw_orientation():
    result = validate_entities([{"id": "arc", "type": "arc", "center": [10, 20], "radius": 5,
                                 "start_angle": -math.pi / 2, "end_angle": 0}])[0]
    assert result["start_angle"] == -math.pi / 2
    assert result["radius"] == 5
    with pytest.raises(CadError, match="sweep"):
        validate_entities([{**result, "end_angle": result["start_angle"] + math.tau}])


def test_closed_polyline_needs_three_vertices():
    with pytest.raises(CadError, match="three"):
        validate_entities([{"type": "polyline", "points": [[0, 0], [1, 1]], "closed": True}])


def test_only_owned_documents_can_be_read_or_modified():
    bridge = CadBridge.__new__(CadBridge)
    bridge._documents = {}
    with pytest.raises(CadError, match="bridge-created"):
        bridge._owned("arbitrary-existing-user-drawing")


def test_output_path_cannot_escape_project_or_overwrite(tmp_path):
    bridge = CadBridge.__new__(CadBridge)
    bridge.data_dir = (tmp_path / "data").resolve()
    bridge.data_dir.mkdir()
    with pytest.raises(CadError, match="inside"):
        bridge._output_path("../outside.dwg")
    with pytest.raises(CadError, match="inside"):
        bridge._output_path(tmp_path / "outside.dwg")
    with pytest.raises(CadError, match="DWG"):
        bridge._output_path("drawing.exe")
    existing = bridge.data_dir / "user.dwg"
    existing.write_bytes(b"original")
    with pytest.raises(CadError, match="already exists"):
        bridge._output_path(existing)
    assert existing.read_bytes() == b"original"
    assert bridge._output_path("cad/new.dwg").parent == bridge.data_dir / "cad"


def test_read_only_inspection_preserves_nonzero_line_elevations():
    bridge = CadBridge.__new__(CadBridge)
    obj = SimpleNamespace(ObjectName="AcDbLine", Handle="AA", Layer="SURVEY",
                          StartPoint=(1, 2, 7), EndPoint=(4, 6, 7), Length=5)
    result = bridge._inspect_entity(obj)
    assert result["start"] == [1, 2, 7] and result["end"] == [4, 6, 7]
    assert result["is_2d_planar"] is False
    assert result["coordinate_system"] == "WCS"


def test_read_only_polyline_preserves_bulges_elevation_and_normal():
    bridge = CadBridge.__new__(CadBridge)
    obj = SimpleNamespace(ObjectName="AcDbPolyline", Handle="AB", Layer="SURVEY",
                          Coordinates=(0, 0, 4, 0, 4, 4), Normal=(0, 0, 1),
                          Elevation=3, Closed=True, Length=15,
                          GetBulge=lambda i: [0.5, 0, -0.5][i])
    result = bridge._inspect_entity(obj)
    assert result["bulges"] == [0.5, 0, -0.5]
    assert result["points"] == [[0, 0], [4, 0], [4, 4]]
    assert result["elevation"] == 3 and result["normal"] == [0, 0, 1]
    assert result["is_2d_planar"] is False


def test_inspect_without_running_cad_does_not_launch_it():
    bridge = CadBridge.__new__(CadBridge)
    calls = []
    bridge._connect = lambda launch: calls.append(launch)
    result = bridge._inspect_active(10)
    assert calls == [False]
    assert result["connected"] is False and result["document"] is None


def test_inspection_limit_is_bounded_before_queueing():
    bridge = CadBridge.__new__(CadBridge)
    for limit in (0, 5001, True, 1.5):
        with pytest.raises(CadError, match="max_entities"):
            bridge.inspect_active(limit)


def test_closed_bridge_fails_immediately_without_queueing():
    bridge = CadBridge.__new__(CadBridge)
    bridge._closed = True
    with pytest.raises(CadError, match="disconnected"):
        bridge.status()


def test_automatic_planar_edits_refuse_unmodelled_geometry():
    assert _editable_xy_entities([{"type": "line", "start_z": 0, "end_z": 0}])
    assert not _editable_xy_entities([{"type": "line", "start_z": 2}])
    assert not _editable_xy_entities([{"type": "arc", "normal": [0, 1, 0]}])
    assert not _editable_xy_entities([{"type": "polyline", "bulges": [0, 0.5]}])
