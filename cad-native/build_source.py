"""Build a source-only QingGuiAI CAD archive from explicit public whitelists.

No binaries, CAD SDK assemblies, runtime, local projects, or private course files
are included. The original engine applies its own standalone source whitelist.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION = "0.3.0"
NAME = f"QingGuiAI-CAD-{VERSION}-source"
ROOT_NAMES = ("PackageContents.xml", "LICENSE", "NOTICE.md", "README.md", "BUILD.md", "build_bundle.py", "build_source.py")
FOLDERS = {
    "native": {".cs", ".csproj", ".md"},
    "installer": {".cs", ".ps1", ".manifest", ".md"},
    "launcher": {".cs", ".ps1", ".ico"},
}
BLOCKED_PARTS = {"bin", "obj", "runtime", "data", "releases", "publish", "node_modules", ".git", ".venv", "__pycache__", ".pytest_cache"}
BLOCKED_SUFFIXES = {".dll", ".exe", ".pyd", ".dwg", ".dxf", ".sqlite", ".sqlite3", ".db", ".pdf", ".png", ".jpg", ".jpeg", ".zip"}
PERSONAL_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]+users[\\/]+[^\\/\s\"']+|/(?:Users|home)/[^/\s\"']+)")


def default_engine() -> Path:
    """Resolve the shared repo engine or an extracted source archive's engine."""
    embedded = ROOT / "engine"
    return embedded if (embedded / "planning_cli.py").is_file() else ROOT.parent


def public_data(path: Path, root: Path) -> bytes:
    relative = path.relative_to(root)
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError(f"Not an ordinary in-scope source file: {relative}")
    if {p.casefold() for p in relative.parts} & BLOCKED_PARTS or path.suffix.lower() in BLOCKED_SUFFIXES:
        raise ValueError(f"Blocked source path: {relative}")
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
            raise ValueError(f"Source path traverses a link: {relative}")
    data = path.read_bytes()
    if path.suffix.lower() != ".ico":
        text = data.decode("utf-8-sig")
        if PERSONAL_PATH.search(text):
            raise ValueError(f"Personal absolute path found: {relative}")
        username = Path.home().name
        if len(username) > 5 and username.casefold() not in {"public", "runner", "codex"} and username.casefold() in text.casefold():
            raise ValueError(f"Local user name found: {relative}")
    return data


def collect(engine: Path) -> tuple[dict[str, bytes], dict]:
    engine = engine.resolve()
    contents: dict[str, bytes] = {}

    def add(relative: str, data: bytes) -> None:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or ":" in relative or "\\" in relative:
            raise ValueError("Invalid archive path: " + relative)
        if relative.casefold() in {name.casefold() for name in contents}:
            raise ValueError("Duplicate archive path: " + relative)
        contents[relative] = data

    for name in ROOT_NAMES:
        add(name, public_data(ROOT / name, ROOT))
    for folder, suffixes in FOLDERS.items():
        for path in sorted((ROOT / folder).rglob("*")):
            relative = path.relative_to(ROOT)
            if path.suffix.lower() not in suffixes or {p.casefold() for p in relative.parts} & BLOCKED_PARTS:
                continue
            add(relative.as_posix(), public_data(path, ROOT))

    # A developer must supply their own AutoCAD SDK directory at build time.
    project = ET.fromstring(contents["native/QingGuiAI.Cad.csproj"])
    for node in project.iter("AutoCADSdkDir"):
        if (node.text or "").strip():
            raise ValueError("Remove the machine-specific default AutoCADSdkDir before distributing source")

    spec = importlib.util.spec_from_file_location("qinggui_engine_release", engine / "build_release.py")
    if spec is None or spec.loader is None:
        raise ValueError("The engine build_release.py is unavailable")
    module = importlib.util.module_from_spec(spec)
    prior_bytecode_setting = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = prior_bytecode_setting
    engine_sources = module.files(True)
    for path in engine_sources:
        relative = path.relative_to(engine)
        data = module._public_bytes(path)
        # Also enforce this archive's blocked paths and regular-file checks.
        if public_data(path, engine) != data:
            raise ValueError("Engine public-source content changed during collection")
        add("engine/" + relative.as_posix(), data)

    provenance = engine / "runtime" / "DEPENDENCIES.json"
    if not provenance.is_file():
        provenance = engine / "provenance" / "DEPENDENCIES.json"
    provenance_included = provenance.is_file()
    if provenance_included:
        data = provenance.read_bytes()
        dependencies = json.loads(data.decode("utf-8-sig"))
        rows = [dependencies["python"], *dependencies["wheels"]]
        for row in rows:
            if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
                raise ValueError("Invalid third-party dependency digest")
            if not row["url"].startswith(("https://www.python.org/", "https://files.pythonhosted.org/", "https://pypi.org/")):
                raise ValueError("Unexpected third-party dependency source URL")
        if PERSONAL_PATH.search(data.decode("utf-8-sig")):
            raise ValueError("Personal path found in dependency provenance")
        add("engine/provenance/DEPENDENCIES.json", data)
        add("engine/provenance/README.md", (
            "# Dependency provenance\n\n"
            "DEPENDENCIES.json records the official CPython and PyPI wheel URLs, versions, SHA-256 hashes and license metadata used for the verified runtime. "
            "This source archive includes no runtime or wheels. Rebuild them using BUILD.md; retained third-party licenses must accompany the binary distribution. "
            "Project MIT terms do not replace dependency licenses.\n"
        ).encode("utf-8"))

    required = {"native/QingGuiAI.Cad.csproj", "native/Commands.cs", "installer/Setup.cs", "installer/Build-Setup.ps1", "launcher/Launcher.cs", "launcher/Shared.cs", "launcher/Uninstall.cs", "launcher/Build-Launcher.ps1", "launcher/QingGuiAI.ico", "engine/planning_cli.py", "engine/build_release.py", "engine/build_windows_portable.py", "engine/requirements.lock.txt", "engine/LICENSE"}
    if required - contents.keys():
        raise ValueError("Missing required source files: " + ", ".join(sorted(required - contents.keys())))
    metadata = {"product": "清规AI · CAD原生插件", "version": VERSION, "engine_version": getattr(module, "VERSION", "unknown"), "engine_source_files": len(engine_sources), "dependency_provenance_included": provenance_included, "runtime_included": False, "cad_sdk_included": False, "private_data_included": False}
    return dict(sorted(contents.items())), metadata


def build(engine: Path, output: Path, check_only: bool = False) -> dict:
    contents, metadata = collect(engine)
    rows = [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in contents.items()]
    if check_only:
        return {**metadata, "source_files": len(contents), "check_only": True}
    output = output.resolve()
    if output.exists():
        raise ValueError("Choose a new output directory; source builds never overwrite previous output")
    output.mkdir(parents=True)
    stage = output / NAME
    stage.mkdir()
    manifest = {**metadata, "files": rows}
    contents["SOURCE-MANIFEST.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    for relative, data in contents.items():
        path = stage / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    archive = output / (NAME + ".zip")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for relative, data in sorted(contents.items()):
            info = zipfile.ZipInfo(NAME + "/" + relative, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            target.writestr(info, data)
    with zipfile.ZipFile(archive) as target:
        if target.testzip() is not None:
            raise ValueError("Source ZIP CRC verification failed")
        for row in rows:
            if hashlib.sha256(target.read(NAME + "/" + row["path"])).hexdigest() != row["sha256"]:
                raise ValueError("Source ZIP hash mismatch: " + row["path"])
    result = {**metadata, "archive": archive.name, "source_files": len(rows), "files_with_manifest": len(contents), "bytes": archive.stat().st_size, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    (output / "source-build.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=default_engine(),
                        help="Engine root; defaults to engine/ in a source archive or the parent repository")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-only", action="store_true", help="Validate the complete whitelist without writing files")
    args = parser.parse_args()
    if not args.check_only and args.output is None:
        parser.error("--output is required unless --check-only is used")
    print(json.dumps(build(args.engine, args.output, args.check_only), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
