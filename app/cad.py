"""AutoCAD ActiveX adapter: all COM objects stay on one dedicated STA thread.

Only drawings created by this bridge can be modified. No arbitrary CAD commands
or caller-provided executable paths are accepted, and AutoCAD is never killed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import queue
import re
import threading
import time
import uuid
from concurrent.futures import Future
from pathlib import Path


class CadError(RuntimeError):
    pass


# ACI colors distinguish planning meaning on AutoCAD's dark model-space canvas.
# Applied only to layers newly created by this bridge; existing layers are left alone.
LAYER_COLORS = {
    "ROAD_CENTER": 1, "ROAD_EDGE": 7, "ROAD_CAP": 7, "ROAD_JUNCTION": 3,
    "EXISTING_ROAD": 8, "CONTEXT": 8, "BLOCK_BOUNDARY": 9,
    "RETAINED_ROAD_EDGE": 3, "RETAINED_ROAD_CAP": 3, "RETAINED_OBJECT": 2,
    "PROPOSED_ROAD_EDGE": 4, "PROPOSED_ROAD_CAP": 4,
    "ROAD_LABEL": 2, "CONSTRAINT": 6,
    "SECTION_SURFACE": 4, "SECTION_DIMENSION": 3, "SECTION_LABEL": 2, "SECTION_CENTER": 1,
    "PARCEL_BOUNDARY": 3, "PARCEL_HOLE": 2, "PARCEL_LABEL": 2,
    "SITE_BOUNDARY": 7, "SITE_EXCLUSION": 2, "PARCEL_ROAD": 8,
    "PARCEL_ROAD_CENTER": 1, "CONTROL_FRAME": 7, "CONTROL_TEXT": 2,
}


def _chinese_font_candidates():
    """Read-only discovery of known Windows Chinese TrueType families."""
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = (("simhei.ttf", "SimHei"), ("msyh.ttc", "Microsoft YaHei"),
                  ("simsun.ttc", "SimSun"), ("Deng.ttf", "DengXian"))
    return [(fonts / filename, family) for filename, family in candidates if (fonts / filename).is_file()]


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def _editable_xy_entities(entities):
    """This writer supports zero-elevation XY geometry and straight polylines."""
    for entity in entities:
        if any(abs(entity.get(key, 0)) > 1e-9 for key in ("start_z", "end_z", "center_z", "position_z", "elevation")):
            return False
        normal = entity.get("normal", [0, 0, 1])
        if len(normal) != 3 or any(abs(a - b) > 1e-9 for a, b in zip(normal, [0, 0, 1])):
            return False
        if any(abs(bulge) > 1e-9 for bulge in entity.get("bulges", [])):
            return False
    return True


def _point(value, name="point"):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise CadError(f"{name} must contain two coordinates")
    result = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise CadError(f"{name} coordinates must be numbers")
        component = float(component)
        if not math.isfinite(component) or abs(component) > 1e8:
            raise CadError(f"{name} coordinate is outside the supported range")
        result.append(component)
    return result


def validate_entities(entities):
    if not isinstance(entities, list) or not 1 <= len(entities) <= 5000:
        raise CadError("A CAD job must contain 1 to 5000 entities")
    output, ids = [], set()
    for index, raw in enumerate(entities):
        if not isinstance(raw, dict):
            raise CadError("Each entity must be an object")
        entity_id = str(raw.get("id", f"entity-{index + 1}"))
        if not entity_id or len(entity_id) > 128 or entity_id in ids:
            raise CadError("Entity ids must be unique and at most 128 characters")
        ids.add(entity_id)
        layer = str(raw.get("layer", "PW_GEOMETRY"))
        if not layer or len(layer) > 100 or re.search(r'[<>/\\":;?*|=,\x00-\x1f]', layer):
            raise CadError("Invalid CAD layer name")
        kind = raw.get("type")
        item = {"id": entity_id, "type": kind, "layer": layer}
        if kind == "line":
            item.update(start=_point(raw.get("start")), end=_point(raw.get("end")))
            if math.dist(item["start"], item["end"]) < 1e-8:
                raise CadError("Zero-length CAD line")
        elif kind == "arc":
            item["center"] = _point(raw.get("center"))
            for field in ("radius", "start_angle", "end_angle"):
                value = raw.get(field)
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                    raise CadError(f"Invalid arc {field}")
                item[field] = float(value)
            if not 0 < item["radius"] <= 1e8:
                raise CadError("Arc radius must be positive")
            if abs((item["end_angle"] - item["start_angle"]) % math.tau) < 1e-9:
                raise CadError("An arc must have a nonzero sweep smaller than a full circle")
        elif kind == "polyline":
            points = raw.get("points")
            if not isinstance(points, list) or not 2 <= len(points) <= 10000:
                raise CadError("Polyline requires 2 to 10000 points")
            item["points"] = [_point(p) for p in points]
            if not isinstance(raw.get("closed", False), bool):
                raise CadError("Polyline closed must be boolean")
            item["closed"] = raw.get("closed", False)
            if item["closed"] and len(item["points"]) < 3:
                raise CadError("Closed polyline requires at least three points")
        elif kind == "text":
            item["position"] = _point(raw.get("position"))
            text = raw.get("text")
            height = raw.get("height", 2.5)
            if not isinstance(text, str) or not text or len(text) > 512 or any(ord(c) < 32 for c in text):
                raise CadError("CAD text requires 1 to 512 printable characters")
            if isinstance(height, bool) or not isinstance(height, (float, int)) or not math.isfinite(height) or not 0 < height <= 10000:
                raise CadError("Invalid CAD text height")
            item.update(text=text, height=float(height))
        else:
            raise CadError(f"Unsupported CAD entity type: {kind}")
        output.append(item)
    return output


def discover_installations():
    """Registry-only discovery, without launching CAD or inspecting credentials."""
    if os.name != "nt":
        return []
    import winreg
    found = []
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as root:
            for index in range(winreg.QueryInfoKey(root)[0]):
                name = winreg.EnumKey(root, index)
                if re.fullmatch(r"AutoCAD\.Application(?:\.\d+(?:\.\d+)?)?", name, re.I):
                    found.append({"progid": name, "product": "AutoCAD", "adapter": "activex"})
    except OSError:
        pass
    return sorted(found, key=lambda x: tuple(int(n) for n in re.findall(r"\d+", x["progid"])), reverse=True)


class CadBridge:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._tasks = queue.Queue()
        self._app = None
        self._documents = {}
        self._boot_error = None
        self._closed = False
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="PlanningCAD-STA", daemon=True)
        self._thread.start()
        self._ready.wait(10)

    def _worker(self):
        self._pythoncom = self._client = None
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            self._pythoncom, self._client = pythoncom, win32com.client
        except Exception as exc:
            self._boot_error = f"Windows pywin32 COM runtime unavailable: {type(exc).__name__}: {exc}"
        self._ready.set()
        while True:
            try:
                task = self._tasks.get(timeout=0.05)
            except queue.Empty:
                if self._pythoncom:
                    self._pythoncom.PumpWaitingMessages()
                continue
            if task is None:
                break
            future, method, args = task
            if not future.set_running_or_notify_cancel():
                continue
            try:
                result = getattr(self, "_" + method)(*args)
                future.set_result(result)
            except Exception as exc:
                future.set_exception(exc if isinstance(exc, CadError) else CadError(f"CAD operation failed: {type(exc).__name__}: {exc}"))
        self._documents.clear()
        self._app = None
        if self._pythoncom:
            self._pythoncom.CoUninitialize()

    def _call(self, method, *args):
        if self._closed or not self._thread.is_alive():
            raise CadError("CAD bridge is disconnected; create a new bridge instance")
        future = Future()
        self._tasks.put((future, method, args))
        # A timed-out HTTP request must not replay a possibly committed COM job.
        # COM jobs remain serial and callers can reconcile using job_id/readback.
        return future.result(timeout=180)

    def status(self):
        return self._call("status")

    def new_document(self):
        return self._call("new_document")

    def read_document(self, document_id):
        return self._call("read_document", str(document_id))

    def inspect_active(self, max_entities=2000):
        """Read current drawing/selection without adopting or changing it.

        LINE/ARC use real WCS 3D positions; LWPOLYLINE returns 2D OCS
        vertices plus elevation, normal and per-vertex bulges. No flattening.
        """
        if isinstance(max_entities, bool) or not isinstance(max_entities, int) or not 1 <= max_entities <= 5000:
            raise CadError("max_entities must be an integer from 1 to 5000")
        return self._call("inspect_active", max_entities)

    def apply(self, document_id, entities, job_id, expected_version=None):
        validated = validate_entities(entities)
        if not isinstance(job_id, str) or not 1 <= len(job_id) <= 128:
            raise CadError("job_id must contain 1 to 128 characters")
        return self._call("apply", str(document_id), validated, job_id, expected_version)

    def undo(self, document_id):
        return self._call("undo", str(document_id))

    def modify(self, document_id, entities, job_id, expected_version=None):
        """Modify existing bridge-created entity ids using complete typed geometry."""
        validated = validate_entities(entities)
        if not isinstance(job_id, str) or not 1 <= len(job_id) <= 128:
            raise CadError("job_id must contain 1 to 128 characters")
        return self._call("modify", str(document_id), validated, job_id, expected_version)

    def save(self, document_id, path):
        return self._call("save", str(document_id), str(path))

    def fit(self, document_id):
        """Fit the current owned drawing only; never activate another drawing."""
        return self._call("fit", str(document_id))

    def _retry(self, function, seconds=12):
        deadline = time.monotonic() + seconds
        while True:
            try:
                return function()
            except Exception as exc:
                # Retry only explicit COM call rejection, never arbitrary failure.
                code = getattr(exc, "hresult", None)
                if code not in (-2147418111, -2147417846) or time.monotonic() >= deadline:
                    raise
                self._pythoncom.PumpWaitingMessages()
                time.sleep(0.15)

    def _connect(self, launch=False):
        if self._boot_error:
            raise CadError(self._boot_error)
        if self._app is not None:
            try:
                self._retry(lambda: self._app.Version)
                return self._app
            except Exception:
                self._app = None
        installations = discover_installations()
        for entry in installations:
            try:
                self._app = self._client.GetActiveObject(entry["progid"])
                self._progid = entry["progid"]
                return self._app
            except Exception:
                continue
        if not launch:
            return None
        if not installations:
            raise CadError("AutoCAD ActiveX is not installed or registered")
        self._progid = installations[0]["progid"]
        self._app = self._client.Dispatch(self._progid)
        self._retry(lambda: setattr(self._app, "Visible", True), seconds=120)
        return self._app

    def _status(self):
        installations = discover_installations()
        result = {"installed": bool(installations), "installations": installations,
                  "connected": False, "running": False, "backend": "autocad-activex",
                  "owned_documents": list(self._documents), "com_thread": "dedicated-STA",
                  "mock": False}
        if self._boot_error:
            result["error"] = self._boot_error
            return result
        try:
            app = self._connect(False)
            if app:
                result.update(connected=True, running=True, version=str(self._retry(lambda: app.Version)),
                              progid=self._progid)
                if int(self._retry(lambda: app.Documents.Count)):
                    active = self._retry(lambda: app.ActiveDocument)
                    active_id = next((doc_id for doc_id, rec in self._documents.items()
                                      if rec["doc"]._oleobj_ == active._oleobj_), None)
                    result["active_document"] = {
                        "name": str(self._retry(lambda: active.Name)),
                        "document_id": active_id, "owned": active_id is not None,
                        "units": int(self._retry(lambda: active.GetVariable("INSUNITS"))),
                        "entity_count": int(self._retry(lambda: active.ModelSpace.Count)),
                    }
        except Exception as exc:
            result["error"] = str(exc)
        return result

    def _owned(self, document_id):
        record = self._documents.get(document_id)
        if not record:
            raise CadError("Unknown document: writes are limited to bridge-created test drawings")
        try:
            self._retry(lambda: record["doc"].Name)
        except Exception as exc:
            raise CadError("The owned CAD drawing is closed or unavailable") from exc
        return record

    def _inspect_entity(self, obj):
        name = str(obj.ObjectName)
        item = {"handle": str(obj.Handle), "object_name": name, "layer": str(obj.Layer)}
        p3 = lambda value: [float(v) for v in value]
        xy_normal = lambda value: len(value) == 3 and all(abs(a - b) <= 1e-9 for a, b in zip(value, [0, 0, 1]))
        if name == "AcDbLine":
            start, end = p3(obj.StartPoint), p3(obj.EndPoint)
            item.update(type="line", start=start, end=end, coordinate_system="WCS",
                        is_2d_planar=abs(start[2]) <= 1e-9 and abs(end[2]) <= 1e-9,
                        length=float(obj.Length))
        elif name == "AcDbArc":
            center, normal = p3(obj.Center), p3(obj.Normal)
            item.update(type="arc", center=center, normal=normal, radius=float(obj.Radius),
                        start_angle=float(obj.StartAngle), end_angle=float(obj.EndAngle),
                        start_point=p3(obj.StartPoint), end_point=p3(obj.EndPoint),
                        arc_length=float(obj.ArcLength), angle_units="radians_ccw",
                        coordinate_system="center/endpoints=WCS; angles=entity OCS",
                        is_2d_planar=abs(center[2]) <= 1e-9 and xy_normal(normal))
        elif name == "AcDbPolyline":
            coordinates = [float(v) for v in obj.Coordinates]
            normal, elevation = p3(obj.Normal), float(obj.Elevation)
            points = [[coordinates[i], coordinates[i + 1]] for i in range(0, len(coordinates), 2)]
            item.update(type="polyline", points=points, closed=bool(obj.Closed),
                        bulges=[float(obj.GetBulge(i)) for i in range(len(points))],
                        elevation=elevation, normal=normal, coordinate_system="OCS",
                        is_2d_planar=abs(elevation) <= 1e-9 and xy_normal(normal), length=float(obj.Length))
        else:
            item.update(type="unsupported", geometry_read=False)
        return item

    def _inspect_active(self, max_entities):
        app = self._connect(False)
        if app is None:
            return {"connected": False, "document": None, "entities": [], "layers": [],
                    "selection": {"source": "PickfirstSelectionSet", "count": 0, "entities": []},
                    "reason": "AutoCAD is not running; read-only inspection does not launch it"}
        if not int(self._retry(lambda: app.Documents.Count)):
            return {"connected": True, "document": None, "entities": [], "layers": [],
                    "selection": {"source": "PickfirstSelectionSet", "count": 0, "entities": []},
                    "reason": "AutoCAD has no open drawing"}
        doc = self._retry(lambda: app.ActiveDocument)
        owned_id = next((key for key, record in self._documents.items() if record["doc"]._oleobj_ == doc._oleobj_), None)
        name = str(self._retry(lambda: doc.Name))
        path = str(self._retry(lambda: doc.FullName))
        hwnd = int(self._retry(lambda: doc.HWND))
        units = int(self._retry(lambda: doc.GetVariable("INSUNITS")))
        native_read_only = bool(self._retry(lambda: doc.ReadOnly))
        active_layer = str(self._retry(lambda: doc.ActiveLayer.Name))
        command_active = int(self._retry(lambda: doc.GetVariable("CMDACTIVE")))
        document = {"identity": "acad-" + _digest([hwnd, path, name])[:24],
                    "document_id": owned_id, "name": name, "path": path, "window_handle": hwnd,
                    "owned": owned_id is not None, "units": units,
                    "unit_name": {0: "unitless", 1: "inches", 2: "feet", 4: "millimetres", 5: "centimetres", 6: "metres"}.get(units, "other"),
                    "active_layer": active_layer, "native_read_only": native_read_only,
                    "bridge_writable": owned_id is not None and not native_read_only and units == 6 and command_active == 0,
                    "command_active": command_active, "active_space": int(self._retry(lambda: doc.ActiveSpace)),
                    "write_policy": "Only drawings created by this bridge instance may be written"}
        layer_count = int(self._retry(lambda: doc.Layers.Count))
        layers = []
        for i in range(min(layer_count, 4096)):
            layer = self._retry(lambda i=i: doc.Layers.Item(i))
            layers.append(self._retry(lambda: {"name": str(layer.Name), "on": bool(layer.LayerOn),
                                               "frozen": bool(layer.Freeze), "locked": bool(layer.Lock),
                                               "color_index": int(layer.Color)}))
        total = int(self._retry(lambda: doc.ModelSpace.Count))
        entities, unsupported = [], []
        for i in range(min(total, max_entities)):
            item = self._retry(lambda i=i: self._inspect_entity(doc.ModelSpace.Item(i)))
            (unsupported if item["type"] == "unsupported" else entities).append(item)
        pickfirst = self._retry(lambda: doc.PickfirstSelectionSet)
        selected_count = int(self._retry(lambda: pickfirst.Count))
        selected = [self._retry(lambda i=i: self._inspect_entity(pickfirst.Item(i)))
                    for i in range(min(selected_count, max_entities))]
        consistent = self._retry(lambda: app.ActiveDocument._oleobj_ == doc._oleobj_)
        if (any(e["object_name"] != "AcDbText" for e in unsupported) or total > max_entities
                or any(not e["is_2d_planar"] for e in entities)
                or any(any(abs(b) > 1e-9 for b in e.get("bulges", [])) for e in entities)):
            document["bridge_writable"] = False
        return {"connected": True, "document": document, "layers": layers, "entities": entities,
                "unsupported_entities": unsupported, "modelspace_count": total,
                "scanned_count": min(total, max_entities), "supported_count": len(entities),
                "truncated": total > max_entities, "layers_truncated": layer_count > 4096,
                "selection": {"source": "PickfirstSelectionSet", "count": selected_count,
                              "entities": selected, "truncated": selected_count > max_entities},
                "active_document_unchanged_during_read": bool(consistent),
                "planarity_definition": "is_2d_planar requires XY plane at elevation zero; other coordinates are preserved, never flattened",
                "read_only": True}

    def _new_document(self):
        app = self._connect(True)
        doc = self._retry(lambda: app.Documents.Add(), seconds=120)
        # Some AutoCAD versions expose the returned document before its symbol
        # tables are ready. Poll that SAME document; never repeat Documents.Add.
        deadline = time.monotonic() + 12
        while True:
            try:
                doc.Name
                doc.TextStyles.Count
                doc.ModelSpace.Count
                break
            except Exception as exc:
                if not isinstance(exc, AttributeError) and getattr(exc, "hresult", None) not in (-2147418111, -2147417846):
                    raise
                if time.monotonic() >= deadline:
                    raise CadError("AutoCAD created a document but its tables are not ready; inspect the new drawing before retrying") from exc
                self._pythoncom.PumpWaitingMessages()
                time.sleep(.15)
        document_id = "pw-" + uuid.uuid4().hex
        self._documents[document_id] = {"doc": doc, "jobs": {}, "history": [], "ids": {}}
        self._retry(lambda: doc.SetVariable("INSUNITS", self._client.VARIANT(self._pythoncom.VT_I2, 6)))
        self._retry(lambda: doc.SetVariable("MEASUREMENT", self._client.VARIANT(self._pythoncom.VT_I2, 1)))
        self._documents[document_id]["text_style"] = self._initialize_text_style(doc)
        result = self._read_document(document_id)
        result.update(created=True, owned=True)
        return result

    def _initialize_text_style(self, doc):
        # A unique name also preserves any style supplied by the user's template.
        name = "PW_Chinese_" + uuid.uuid4().hex[:8]
        candidates = _chinese_font_candidates()
        if not candidates:
            raise CadError("No supported Windows Chinese TrueType font is installed")
        style = self._retry(lambda: doc.TextStyles.Add(name))
        accepted = False
        try:
            for font, family in candidates:
                try:
                    self._retry(lambda: setattr(style, "FontFile", str(font)))
                    self._retry(lambda: style.SetFont(family, False, False, 134, 0))
                    actual = str(self._retry(lambda: style.FontFile))
                    if Path(actual).name.casefold() != font.name.casefold():
                        continue
                    self._retry(lambda: setattr(style, "Height", 0.0))
                    self._retry(lambda: setattr(style, "Width", 1.0))
                    self._retry(lambda: setattr(style, "ObliqueAngle", 0.0))
                    self._retry(lambda: setattr(doc, "ActiveTextStyle", style))
                    accepted = True
                    return {"name": name, "font_file": actual, "family": family, "chinese_truetype": True}
                except Exception:
                    continue
            raise CadError("AutoCAD could not confirm an installed Chinese TrueType font")
        finally:
            if not accepted:
                try:
                    self._retry(lambda: style.Delete())
                except Exception:
                    pass

    def _configure_new_layer(self, layer, name):
        for field, value in (("Color", LAYER_COLORS.get(name, 7)), ("LayerOn", True),
                             ("Freeze", False), ("Lock", False)):
            self._retry(lambda f=field, v=value: setattr(layer, f, v))

    def _fit(self, document_id):
        doc = self._owned(document_id)["doc"]
        result = {"document_id": document_id, "fitted": False, "activated_document": False}
        try:
            def zoom_if_current():
                if self._app.ActiveDocument._oleobj_ != doc._oleobj_:
                    return "not_active_document"
                if int(doc.GetVariable("CMDACTIVE")) != 0:
                    return "cad_command_active"
                if int(doc.ActiveSpace) != 1:
                    return "not_model_space"
                if int(doc.ModelSpace.Count) == 0:
                    return "empty_drawing"
                # ZoomExtents is application-scoped, so recheck on every retry.
                self._app.ZoomExtents()
                return None
            reason = self._retry(zoom_if_current)
            if reason:
                return {**result, "reason": reason}
            result.update(fitted=True, method="ZoomExtents")
            # Best-effort diagnostics are independent of the successful zoom.
            try:
                result["view_height"] = float(self._retry(lambda: doc.GetVariable("VIEWSIZE")))
                result["view_center"] = [float(v) for v in self._retry(lambda: doc.GetVariable("VIEWCTR"))]
            except Exception:
                pass
            return result
        except Exception as exc:
            return {**result, "reason": "zoom_failed", "error": str(exc)}

    def _array(self, numbers):
        return self._client.VARIANT(self._pythoncom.VT_ARRAY | self._pythoncom.VT_R8,
                                    [float(v) for v in numbers])

    def _p3(self, point):
        return self._array([point[0], point[1], 0.0])

    def _entity_info(self, obj, ids):
        kind = str(obj.ObjectName)
        handle = str(obj.Handle)
        item = {"id": ids.get(handle, handle), "handle": handle, "object_name": kind,
                "layer": str(obj.Layer), "color_index": int(obj.Color)}
        point = lambda p: [round(float(v), 8) for v in list(p)[:2]]
        if kind == "AcDbLine":
            item.update(type="line", start=point(obj.StartPoint), end=point(obj.EndPoint),
                        start_z=round(float(obj.StartPoint[2]), 8), end_z=round(float(obj.EndPoint[2]), 8))
        elif kind == "AcDbArc":
            item.update(type="arc", center=point(obj.Center), radius=round(float(obj.Radius), 8),
                        start_angle=round(float(obj.StartAngle), 8), end_angle=round(float(obj.EndAngle), 8),
                        center_z=round(float(obj.Center[2]), 8), normal=[round(float(v), 8) for v in obj.Normal])
        elif kind == "AcDbPolyline":
            coords = list(obj.Coordinates)
            item.update(type="polyline", points=[[round(float(coords[i]), 8), round(float(coords[i + 1]), 8)]
                                                 for i in range(0, len(coords), 2)], closed=bool(obj.Closed),
                        elevation=round(float(obj.Elevation), 8), normal=[round(float(v), 8) for v in obj.Normal],
                        bulges=[round(float(obj.GetBulge(i)), 8) for i in range(len(coords) // 2)])
        elif kind == "AcDbText":
            item.update(type="text", position=point(obj.InsertionPoint), text=str(obj.TextString),
                        height=round(float(obj.Height), 8), position_z=round(float(obj.InsertionPoint[2]), 8),
                        style_name=str(obj.StyleName))
        else:
            item["type"] = "unsupported"
        return item

    def _read_document(self, document_id):
        record = self._owned(document_id)
        doc = record["doc"]
        count = int(self._retry(lambda: doc.ModelSpace.Count))
        if count > 20000:
            raise CadError("Owned drawing exceeds the 20000-entity readback limit")
        entities = [self._retry(lambda i=i: self._entity_info(doc.ModelSpace.Item(i), record["ids"]))
                    for i in range(count)]
        layer_details = []
        for i in range(int(self._retry(lambda: doc.Layers.Count))):
            layer = self._retry(lambda i=i: doc.Layers.Item(i))
            layer_details.append(self._retry(lambda: {"name": str(layer.Name), "color_index": int(layer.Color),
                                                      "on": bool(layer.LayerOn), "frozen": bool(layer.Freeze),
                                                      "locked": bool(layer.Lock)}))
        layers = [layer["name"] for layer in layer_details]
        units = int(self._retry(lambda: doc.GetVariable("INSUNITS")))
        snapshot = {"entities": sorted(entities, key=lambda e: e["handle"]),
                    "layers": sorted(layers), "layer_details": sorted(layer_details, key=lambda e: e["name"]),
                    "units": units}
        if record.get("text_style"):
            style = self._retry(lambda: doc.TextStyles.Item(record["text_style"]["name"]))
            snapshot["text_style"] = self._retry(lambda: {"name": str(style.Name), "font_file": str(style.FontFile),
                                                          "height": float(style.Height), "width": float(style.Width)})
        return {"document_id": document_id, "name": str(self._retry(lambda: doc.Name)),
                "owned": True, "entity_count": count, "unit_name": "metres" if units == 6 else "other",
                "version": _digest(snapshot), **snapshot}

    def _add(self, doc, item):
        model = doc.ModelSpace
        if item["type"] == "line":
            obj = self._retry(lambda: model.AddLine(self._p3(item["start"]), self._p3(item["end"])))
        elif item["type"] == "arc":
            obj = self._retry(lambda: model.AddArc(self._p3(item["center"]), item["radius"], item["start_angle"], item["end_angle"]))
        elif item["type"] == "polyline":
            obj = self._retry(lambda: model.AddLightWeightPolyline(self._array([v for p in item["points"] for v in p])))
        else:
            obj = self._retry(lambda: model.AddText(item["text"], self._p3(item["position"]), item["height"]))
        try:
            if item["type"] == "polyline":
                self._retry(lambda: setattr(obj, "Closed", item["closed"]))
            if item["type"] == "text":
                record = next(r for r in self._documents.values() if r["doc"]._oleobj_ == doc._oleobj_)
                self._retry(lambda: setattr(obj, "StyleName", record["text_style"]["name"]))
                self._retry(lambda: setattr(obj, "TextString", item["text"]))
            self._retry(lambda: setattr(obj, "Layer", item["layer"]))
            self._retry(lambda: setattr(obj, "Color", 256))  # ByLayer, independent of CECOLOR/template defaults.
        except Exception:
            self._retry(lambda: obj.Delete())
            raise
        return obj

    def _set_geometry(self, obj, item):
        if item["type"] == "line":
            values = {"StartPoint": self._p3(item["start"]), "EndPoint": self._p3(item["end"])}
        elif item["type"] == "arc":
            values = {"Center": self._p3(item["center"]), "Radius": item["radius"],
                      "StartAngle": item["start_angle"], "EndAngle": item["end_angle"]}
        elif item["type"] == "polyline":
            values = {"Coordinates": self._array([v for p in item["points"] for v in p]), "Closed": item["closed"]}
        else:
            values = {"InsertionPoint": self._p3(item["position"]), "TextString": item["text"], "Height": item["height"]}
        values["Layer"] = item["layer"]
        for field, value in values.items():
            self._retry(lambda f=field, v=value: setattr(obj, f, v))

    def _modify(self, document_id, entities, job_id, expected_version):
        record = self._owned(document_id)
        job_hash = _digest({"operation": "modify", "entities": entities})
        if job_id in record["jobs"]:
            saved = record["jobs"][job_id]
            if saved["input_hash"] != job_hash or saved.get("undone"):
                raise CadError("job_id is already used or undone")
            state = self._read_document(document_id)
            return {**copy.deepcopy(saved["result"]), "idempotent": True, "readback": state, "version": state["version"]}
        before = self._read_document(document_id)
        if before["units"] != 6:
            raise CadError("This adapter writes metres only; drawing INSUNITS must be 6")
        if not _editable_xy_entities(before["entities"]):
            raise CadError("Drawing contains nonzero elevation, tilted geometry or bulged polylines; automatic editing refused")
        if expected_version is not None and expected_version != before["version"]:
            raise CadError("Drawing changed: version conflict. Read the drawing and confirm again.")
        if any(e["type"] == "unsupported" for e in before["entities"]):
            raise CadError("Drawing contains unsupported entity types; automatic modification refused")
        by_id = {e["id"]: e for e in before["entities"] if e["handle"] in record["ids"]}
        for item in entities:
            original = by_id.get(item["id"])
            if not original or original["type"] != item["type"]:
                raise CadError("Modification requires an existing bridge entity with the same type")
            if item["layer"] not in before["layers"]:
                raise CadError("Modification layer must already exist")
        doc = record["doc"]
        if int(self._retry(lambda: doc.GetVariable("CMDACTIVE"))) != 0:
            raise CadError("Finish the current CAD command before modifying")
        self._retry(lambda: doc.StartUndoMark())
        touched = []
        try:
            for item in entities:
                original = by_id[item["id"]]
                obj = self._retry(lambda: doc.HandleToObject(original["handle"]))
                touched.append((obj, original))
                self._set_geometry(obj, item)
            self._retry(lambda: doc.Regen(1))
            view = self._fit(document_id)
        except Exception:
            for obj, original in reversed(touched):
                self._set_geometry(obj, original)
            raise
        finally:
            self._retry(lambda: doc.EndUndoMark())
        after = self._read_document(document_id)
        result = {"document_id": document_id, "job_id": job_id, "modified": len(entities),
                  "applied": True, "idempotent": False, "version": after["version"], "readback": after,
                  "view": view}
        record["jobs"][job_id] = {"input_hash": job_hash, "result": copy.deepcopy(result), "undone": False}
        record["history"].append({"job_id": job_id, "before": before, "after": after})
        return result

    def _apply(self, document_id, entities, job_id, expected_version):
        record = self._owned(document_id)
        job_hash = _digest(entities)
        if job_id in record["jobs"]:
            saved = record["jobs"][job_id]
            if saved["input_hash"] != job_hash:
                raise CadError("job_id was already used with a different input")
            if saved.get("undone"):
                raise CadError("This job was undone; use a new job_id to apply it again")
            state = self._read_document(document_id)
            return {**copy.deepcopy(saved["result"]), "idempotent": True,
                    "readback": state, "version": state["version"]}
        before = self._read_document(document_id)
        if before["units"] != 6:
            raise CadError("This adapter writes metres only; drawing INSUNITS must be 6")
        if not _editable_xy_entities(before["entities"]):
            raise CadError("Drawing contains nonzero elevation, tilted geometry or bulged polylines; automatic writing refused")
        if expected_version is not None and before["version"] != expected_version:
            raise CadError("Drawing changed: version conflict. Read the drawing and confirm again.")
        if any(e["type"] == "unsupported" for e in before["entities"]):
            raise CadError("Drawing contains unsupported entity types; automatic writing refused")
        existing_ids = {e["id"] for e in before["entities"]}
        if existing_ids.intersection(e["id"] for e in entities):
            raise CadError("Entity id already exists; use modify for an existing bridge entity")
        doc = record["doc"]
        if int(self._retry(lambda: doc.GetVariable("CMDACTIVE"))) != 0:
            raise CadError("CAD is processing an interactive command; finish or cancel it first")
        created, new_layers = [], []
        self._retry(lambda: doc.StartUndoMark())
        try:
            known = set(before["layers"])
            for item in entities:
                if item["layer"] not in known:
                    layer = self._retry(lambda: doc.Layers.Add(item["layer"]))
                    known.add(item["layer"])
                    new_layers.append(layer)
                    self._configure_new_layer(layer, item["layer"])
                obj = self._add(doc, item)
                created.append(obj)
                handle = str(self._retry(lambda: obj.Handle))
                record["ids"][handle] = item["id"]
            self._retry(lambda: doc.Regen(1))
            view = self._fit(document_id)
        except Exception:
            for obj in reversed(created):
                try:
                    handle = str(self._retry(lambda: obj.Handle))
                    self._retry(lambda: obj.Delete())
                    record["ids"].pop(handle, None)
                except Exception:
                    pass
            for layer in reversed(new_layers):
                try:
                    self._retry(lambda: layer.Delete())
                except Exception:
                    pass
            raise
        finally:
            self._retry(lambda: doc.EndUndoMark())
        after = self._read_document(document_id)
        if after["entity_count"] != before["entity_count"] + len(entities):
            raise CadError("Readback entity count does not match the committed CAD job")
        result = {"document_id": document_id, "job_id": job_id, "applied": True,
                  "idempotent": False, "added": len(entities), "version": after["version"],
                  "readback": after, "view": view}
        record["jobs"][job_id] = {"input_hash": job_hash, "result": copy.deepcopy(result), "undone": False}
        record["history"].append({"job_id": job_id, "before": before, "after": after})
        return result

    def _undo(self, document_id):
        record = self._owned(document_id)
        if not record["history"]:
            raise CadError("There is no bridge job to undo")
        previous = record["history"][-1]
        current = self._read_document(document_id)
        if current["version"] != previous["after"]["version"]:
            raise CadError("Drawing changed outside the bridge; automatic undo refused")
        doc = record["doc"]
        self._retry(lambda: doc.Activate())
        if int(self._retry(lambda: doc.GetVariable("CMDACTIVE"))) != 0:
            raise CadError("Finish the current CAD command before undo")
        self._retry(lambda: doc.SendCommand("_.U\n"))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            self._pythoncom.PumpWaitingMessages()
            time.sleep(0.1)
            state = self._read_document(document_id)
            if state["version"] == previous["before"]["version"]:
                record["history"].pop()
                record["jobs"][previous["job_id"]]["undone"] = True
                return {"document_id": document_id, "undone": True,
                        "job_id": previous["job_id"], "readback": state, "version": state["version"]}
        raise CadError("CAD undo could not be verified; inspect and read the drawing before continuing")

    def _output_path(self, path):
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.data_dir / candidate
        candidate = candidate.resolve()
        if not candidate.is_relative_to(self.data_dir) or candidate.suffix.lower() != ".dwg":
            raise CadError("DWG output must be inside this project's data directory")
        if candidate.exists():
            raise CadError("Output already exists; choose a new DWG filename")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def _save(self, document_id, path):
        record = self._owned(document_id)
        candidate = self._output_path(path)
        self._retry(lambda: record["doc"].SaveAs(str(candidate)))
        if not candidate.is_file() or candidate.stat().st_size == 0:
            raise CadError("CAD did not produce a nonempty DWG file")
        return {"document_id": document_id, "saved": True, "path": str(candidate),
                "bytes": candidate.stat().st_size, "readback": self._read_document(document_id)}

    def close(self):
        """Release this bridge's COM references, never close/kill the user's CAD."""
        if self._closed:
            return
        self._closed = True
        self._tasks.put(None)
        self._thread.join(timeout=5)
