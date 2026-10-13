from types import SimpleNamespace

import pytest

from app.cad import CadBridge, CadError, LAYER_COLORS


def fit_bridge(*, active=True, count=2, command=0, space=1, zoom_error=False):
    bridge = CadBridge.__new__(CadBridge)
    doc = SimpleNamespace(_oleobj_=object(), Name="owned.dwg", ModelSpace=SimpleNamespace(Count=count),
                          ActiveSpace=space, GetVariable=lambda key: {"CMDACTIVE": command,
                              "VIEWSIZE": 100.0, "VIEWCTR": (0.0, 0.0)}[key])
    bridge._documents = {"owned": {"doc": doc}}
    bridge._retry = lambda action, **kwargs: action()
    calls = []
    def zoom():
        calls.append("zoom")
        if zoom_error:
            raise RuntimeError("controlled view failure")
    bridge._app = SimpleNamespace(ActiveDocument=doc if active else SimpleNamespace(_oleobj_=object()), ZoomExtents=zoom)
    return bridge, calls


def test_fit_current_document_reports_view_without_activation():
    bridge, calls = fit_bridge()
    result = bridge._fit("owned")
    assert result["fitted"] and result["activated_document"] is False
    assert calls == ["zoom"] and result["view_height"] == 100


@pytest.mark.parametrize("kwargs,reason", [({"active": False}, "not_active_document"),
    ({"count": 0}, "empty_drawing"), ({"command": 1}, "cad_command_active"),
    ({"space": 0}, "not_model_space")])
def test_fit_never_changes_another_view_or_interrupts_commands(kwargs, reason):
    bridge, calls = fit_bridge(**kwargs)
    result = bridge._fit("owned")
    assert result["fitted"] is False and result["reason"] == reason and not calls


def test_view_failure_is_explicit_and_does_not_raise_geometry_failure():
    bridge, _ = fit_bridge(zoom_error=True)
    result = bridge._fit("owned")
    assert result["fitted"] is False and result["reason"] == "zoom_failed"
    with pytest.raises(CadError, match="bridge-created"):
        bridge._fit("user-original")


def test_new_layers_are_visible_unlocked_and_semantically_colored():
    bridge = CadBridge.__new__(CadBridge)
    bridge._retry = lambda action, **kwargs: action()
    colors = []
    for name in ("EXISTING_ROAD", "RETAINED_ROAD_EDGE", "PROPOSED_ROAD_EDGE", "ROAD_LABEL"):
        layer = SimpleNamespace(Color=7, LayerOn=False, Freeze=True, Lock=True)
        bridge._configure_new_layer(layer, name)
        assert layer.LayerOn and not layer.Freeze and not layer.Lock
        assert layer.Color == LAYER_COLORS[name]
        colors.append(layer.Color)
    assert len(set(colors)) == 4


def test_font_initialization_adds_isolated_style_without_mutating_standard(monkeypatch, tmp_path):
    font = tmp_path / "simhei.ttf"
    font.write_bytes(b"font fixture; not used by real CAD")
    monkeypatch.setattr("app.cad._chinese_font_candidates", lambda: [(font, "SimHei")])
    standard = SimpleNamespace(Name="Standard", FontFile="txt.shx", Height=0.0, Width=1.0)
    created = []
    class Styles:
        def Add(self, name):
            style = SimpleNamespace(Name=name, SetFont=lambda *args: None)
            created.append(style)
            return style
    doc = SimpleNamespace(TextStyles=Styles(), ActiveTextStyle=standard)
    bridge = CadBridge.__new__(CadBridge)
    bridge._retry = lambda action, **kwargs: action()
    result = bridge._initialize_text_style(doc)
    assert result["name"].startswith("PW_Chinese_")
    assert doc.ActiveTextStyle is created[0] and standard.FontFile == "txt.shx"
    assert created[0].FontFile == str(font) and created[0].Height == 0


def test_makepy_fontfile_spelling_supports_initialization_and_owned_readback(monkeypatch, tmp_path):
    """AutoCAD 2025's generated wrapper exposes fontFile, not FontFile."""
    font = tmp_path / "simhei.ttf"
    font.write_bytes(b"font fixture; not used by real CAD")
    monkeypatch.setattr("app.cad._chinese_font_candidates", lambda: [(font, "SimHei")])

    class CachedStyle:
        __slots__ = ("Name", "fontFile", "Height", "Width", "ObliqueAngle")
        _prop_map_get_ = {"Name": (), "fontFile": (), "Height": (), "Width": ()}

        def __init__(self, name):
            self.Name, self.fontFile = name, "txt.shx"

        def SetFont(self, family, bold, italic, charset, pitch):
            assert family == "SimHei" and self.fontFile == str(font)
            self.fontFile = "simhei.ttf"

    created = []

    class Styles:
        def Add(self, name):
            style = CachedStyle(name)
            created.append(style)
            return style

        def Item(self, name):
            return next(style for style in created if style.Name == name)

    standard = SimpleNamespace(Name="Standard", FontFile="txt.shx")
    doc = SimpleNamespace(TextStyles=Styles(), ActiveTextStyle=standard, Name="owned.dwg",
                          ModelSpace=SimpleNamespace(Count=0), Layers=SimpleNamespace(Count=0),
                          GetVariable=lambda name: 6)
    bridge = CadBridge.__new__(CadBridge)
    bridge._retry = lambda action, **kwargs: action()
    style_result = bridge._initialize_text_style(doc)
    bridge._documents = {"owned": {"doc": doc, "ids": {}, "text_style": style_result}}
    readback = bridge._read_document("owned")
    assert style_result["chinese_truetype"] and style_result["font_file"] == "simhei.ttf"
    assert readback["text_style"]["font_file"] == "simhei.ttf"
    assert doc.ActiveTextStyle is created[0] and standard.FontFile == "txt.shx"


def test_font_failure_retains_operation_cause_and_cleans_only_created_style(monkeypatch, tmp_path):
    font = tmp_path / "simhei.ttf"
    font.write_bytes(b"font fixture; not used by real CAD")
    monkeypatch.setattr("app.cad._chinese_font_candidates", lambda: [(font, "SimHei")])
    deleted = []

    def fail_set_font(*args):
        raise RuntimeError("controlled COM font failure")

    style = SimpleNamespace(SetFont=fail_set_font, Delete=lambda: deleted.append(True))
    standard = SimpleNamespace(Name="Standard", FontFile="txt.shx")
    doc = SimpleNamespace(TextStyles=SimpleNamespace(Add=lambda name: style), ActiveTextStyle=standard)
    bridge = CadBridge.__new__(CadBridge)
    bridge._retry = lambda action, **kwargs: action()
    with pytest.raises(CadError, match="simhei.ttf: set_font: RuntimeError: controlled COM font failure"):
        bridge._initialize_text_style(doc)
    assert deleted == [True] and doc.ActiveTextStyle is standard


def test_font_substitution_is_still_rejected(monkeypatch, tmp_path):
    font = tmp_path / "simhei.ttf"
    font.write_bytes(b"font fixture; not used by real CAD")
    monkeypatch.setattr("app.cad._chinese_font_candidates", lambda: [(font, "SimHei")])
    deleted = []
    style = SimpleNamespace(Delete=lambda: deleted.append(True))
    style.SetFont = lambda *args: setattr(style, "FontFile", "txt.shx")
    standard = SimpleNamespace(Name="Standard", FontFile="txt.shx")
    doc = SimpleNamespace(TextStyles=SimpleNamespace(Add=lambda name: style), ActiveTextStyle=standard)
    bridge = CadBridge.__new__(CadBridge)
    bridge._retry = lambda action, **kwargs: action()
    with pytest.raises(CadError, match="readback_mismatch.*txt.shx"):
        bridge._initialize_text_style(doc)
    assert deleted == [True] and doc.ActiveTextStyle is standard
