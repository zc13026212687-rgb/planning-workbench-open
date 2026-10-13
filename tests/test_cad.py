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


def test_connect_rewraps_cached_active_application_in_dynamic_dispatch(monkeypatch):
    bridge = CadBridge.__new__(CadBridge)
    bridge._boot_error, bridge._app = None, None
    raw_dispatch = object()
    dynamic_app = SimpleNamespace(Version="25.0")
    calls = []
    bridge._retry = lambda action, **kwargs: action()
    bridge._client = SimpleNamespace(
        GetActiveObject=lambda progid: SimpleNamespace(_oleobj_=raw_dispatch),
        dynamic=SimpleNamespace(Dispatch=lambda raw: calls.append(raw) or dynamic_app))
    monkeypatch.setattr("app.cad.discover_installations", lambda: [{"progid": "AutoCAD.Application.25"}])
    assert bridge._connect(False) is dynamic_app
    assert bridge._connect(False) is dynamic_app
    assert calls == [raw_dispatch]


def test_launch_uses_dynamic_dispatch_without_cached_client_factory(monkeypatch):
    bridge = CadBridge.__new__(CadBridge)
    bridge._boot_error, bridge._app = None, None
    calls = []
    dynamic_app = SimpleNamespace(Visible=False)
    bridge._retry = lambda action, **kwargs: action()

    def unavailable(progid):
        raise RuntimeError("No running instance")

    bridge._client = SimpleNamespace(GetActiveObject=unavailable,
        dynamic=SimpleNamespace(Dispatch=lambda progid: calls.append(progid) or dynamic_app))
    monkeypatch.setattr("app.cad.discover_installations", lambda: [{"progid": "AutoCAD.Application.25"}])
    assert bridge._connect(False) is None and not calls
    assert bridge._connect(True) is dynamic_app and dynamic_app.Visible
    assert calls == ["AutoCAD.Application.25"]


def test_owned_readback_normalizes_cached_item_results_and_never_uses_com_iterator():
    class ItemOnly:
        def __init__(self, items):
            self.items, self.Count = items, len(items)

        def Item(self, index):
            return self.items[index]

        def __iter__(self):
            raise AssertionError("COM iteration can reintroduce cached wrappers")

    layer = SimpleNamespace(Name="ROAD_EDGE", Color=7, LayerOn=True, Freeze=False, Lock=False)
    entity = SimpleNamespace(ObjectName="AcDbLine", Handle="1", Layer="ROAD_EDGE", Color=256,
                             StartPoint=(0, 0, 0), EndPoint=(10, 0, 0))
    # Even dynamic collections may return generated wrappers from Item().
    layer_handle, entity_handle = object(), object()
    cached_layer, cached_entity = SimpleNamespace(_oleobj_=layer_handle), SimpleNamespace(_oleobj_=entity_handle)
    objects = {layer_handle: layer, entity_handle: entity}
    doc = SimpleNamespace(Name="owned.dwg", ModelSpace=ItemOnly([cached_entity]), Layers=ItemOnly([cached_layer]),
                          GetVariable=lambda key: 6)
    bridge = CadBridge.__new__(CadBridge)
    bridge._client = SimpleNamespace(dynamic=SimpleNamespace(Dispatch=objects.__getitem__))
    bridge._documents = {"owned": {"doc": doc, "ids": {"1": "road-edge"}}}
    result = bridge._read_document("owned")
    assert result["entity_count"] == 1
    assert result["layer_details"][0]["color_index"] == 7
    assert result["entities"][0]["color_index"] == 256


def test_com_result_boundary_preserves_scalar_and_container_results():
    bridge = CadBridge.__new__(CadBridge)
    bridge._client = SimpleNamespace(dynamic=SimpleNamespace(Dispatch=lambda value: pytest.fail("Not a COM object")))
    for value in (None, 6, "simhei.ttf", (1.0, 2.0, 0.0), {"count": 2}):
        assert bridge._retry(lambda: value) is value


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
