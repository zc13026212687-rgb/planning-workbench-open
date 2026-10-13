"""Versioned source-only distribution with an explicit portable-file whitelist."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = "0.2.0"
BLOCKED_PARTS = {".venv", "runtime", "node_modules", "data", "evidence", "bin", "obj", "__pycache__", ".git", ".pytest_cache", "publish", "releases"}
BLOCKED_NAMES = {"source-manifest.json", "local-engine.json", "server.json", ".env"}
SOURCE_FOLDERS = {
    "app": {".py"}, "skills": {".py", ".json", ".md", ".yaml", ".yml"},
    "references": {".json", ".md"}, "tests": {".py", ".json"},
    "examples": {".json", ".md"}, "docs": {".md", ".py"},
}
BASE_NAMES = ["planning_cli.py", "planning_mcp.py", "requirements.lock.txt", "pytest.ini", "LICENSE", "README.md",
              "build_release.py", "build_windows_portable.py", "install_skills.py", ".gitignore"]
FULL_NAMES = ["run_server.py", "启动清规AI.cmd", "安装清规AI.cmd",
              "desktop/InstallQingGui.ps1", "desktop/LaunchQingGui.ps1", "启动规绘.cmd", "检查与安装依赖.cmd", "desktop/Setup.ps1",
              "启动地块与图则.cmd", "desktop/LaunchRegulatory.ps1", "web/regulatory.html", "web/package.json",
              "web/package-lock.json", "web/tsconfig.json", "web/vite.config.ts", "web/index.html"]

def _allowed(path):
    relative = path.relative_to(ROOT)
    return (path.is_file() and not path.is_symlink() and not set(relative.parts).intersection(BLOCKED_PARTS)
            and path.name not in BLOCKED_NAMES and not path.name.startswith(".env."))

def files(standalone=False):
    paths = []
    for folder, suffixes in SOURCE_FOLDERS.items():
        for path in (ROOT / folder).rglob("*"):
            if path.suffix in suffixes and _allowed(path):
                paths.append(path)
    names = list(BASE_NAMES)
    if not standalone:
        names += FULL_NAMES
        paths += [p for p in (ROOT / "desktop").iterdir() if p.suffix in (".cs", ".csproj", ".xaml") and _allowed(p)]
        paths += [p for p in (ROOT / "web" / "src").rglob("*") if p.suffix in (".ts", ".tsx", ".css", ".json", ".svg") and _allowed(p)]
    paths += [ROOT / name for name in names if _allowed(ROOT / name)]
    return sorted(set(paths), key=lambda path: path.relative_to(ROOT).as_posix())

def _public_bytes(path):
    data = path.read_bytes()
    text = data.decode("utf-8-sig")
    # Identify personal paths; generic installation examples and system fonts
    # remain portable public source.
    personal_path = re.compile(r"(?i)(?:[a-z]:[\\/]+users[\\/]+[^\\/\s\"']+|/(?:Users|home)/[^/\s\"']+)")
    if personal_path.search(text):
        raise ValueError(f"Personal absolute path found in public source: {path.relative_to(ROOT)}")
    username = Path.home().name
    if len(username) > 5 and username not in {"public", "runner", "codex"} and username.casefold() in text.casefold():
        raise ValueError(f"Local user name found in public source: {path.relative_to(ROOT)}")
    return data

def build(output: Path):
    # Inspect all selected files before creating an archive.
    prepared = []
    for standalone, name in ((False, "PlanningWorkbench_Open-source"), (True, "PlanningCAD_Open-skills")):
        contents = [(path.relative_to(ROOT).as_posix(), _public_bytes(path)) for path in files(standalone)]
        required = {"planning_mcp.py", "examples/regulatory-parcels.json", "skills/regulatory-suite/SKILL.md",
                    "docs/mcp-usage.md", "docs/release-0.2.0.md", "docs/open-implementation.md"}
        if not standalone:
            required.update({"web/regulatory.html", "启动地块与图则.cmd", "desktop/LaunchRegulatory.ps1",
                             "启动清规AI.cmd", "安装清规AI.cmd", "desktop/InstallQingGui.ps1", "desktop/LaunchQingGui.ps1"})
        missing = required - {relative for relative, _ in contents}
        if missing:
            raise ValueError("Release is missing required source files: " + ", ".join(sorted(missing)))
        prepared.append((name, contents))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    records = []
    for name, contents in prepared:
        target = output / f"{name}-{VERSION}-{stamp}.zip"
        manifest = [{"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for relative, data in contents]
        with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
            for relative, data in contents:
                archive.writestr(name + "/" + relative, data)
            archive.writestr(name + "/source-manifest.json", json.dumps({"version": VERSION, "files": manifest,
                                                                         "private_data_included": False}, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(target) as archive:
            if archive.testzip() is not None:
                raise ValueError("Archive integrity check failed")
            for member in archive.namelist():
                if set(Path(member).parts).intersection(BLOCKED_PARTS) or member.endswith((".dwg", ".db", ".sqlite3", ".png", ".pdf", ".exe", ".dll")):
                    raise ValueError("Disallowed file entered archive: " + member)
            for row in manifest:
                actual = archive.read(name + "/" + row["path"])
                if hashlib.sha256(actual).hexdigest() != row["sha256"]:
                    raise ValueError("Archive hash verification failed")
        records.append({"file": target.name, "version": VERSION, "bytes": target.stat().st_size,
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "files": len(manifest),
                        "private_data_included": False})
    (output / "latest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return records

def main(argv=None):
    parser = argparse.ArgumentParser(description="只打包可公开的原创源码；不执行GitHub发布")
    parser.add_argument("--out", type=Path, default=ROOT / "releases")
    args = parser.parse_args(argv)
    print(json.dumps(build(args.out), ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
