"""Build an audited Windows x64 bundle from public source and verified dependencies.

Run with a build Python that has pip. The shipped embedded Python does not need pip.
No user data, existing virtual environment, vendor program, or CAD runtime is copied.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

import build_release

ROOT = Path(__file__).resolve().parent
PYTHON_URL = "https://www.python.org/ftp/python/3.14.4/python-3.14.4-embed-amd64.zip"
PYTHON_SHA256 = "cda80a9b1e75c0f1b4f9872ca1b417f0d19bce32facc811aea9180e70fad5fb9"
NAME = "QingGui-AI-0.2.0-windows-x64"


def digest(path):
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_extract(archive, destination):
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if not target.is_relative_to(destination.resolve()):
            raise ValueError("Archive path escapes destination")
    archive.extractall(destination)


def verify_wheel(path):
    with zipfile.ZipFile(path) as archive:
        metadata = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        if len(metadata) != 1 or archive.testzip() is not None:
            raise ValueError("Invalid wheel: " + path.name)
        info = BytesParser().parsebytes(archive.read(metadata[0]))
    name, version = info["Name"], info["Version"]
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
        published = json.load(response)
    matches = [row for row in published["urls"] if row["filename"] == path.name]
    actual = digest(path)
    if len(matches) != 1 or actual != matches[0]["digests"]["sha256"]:
        raise ValueError("Wheel does not match the official PyPI digest: " + path.name)
    return {"name": name, "version": version, "file": path.name, "sha256": actual,
            "url": matches[0]["url"], "license": info.get("License-Expression") or info.get("License", "See package license files")}


def prepare_runtime(archive_path, wheels, target):
    if target.exists():
        raise ValueError("Runtime output must not already exist")
    if digest(archive_path) != PYTHON_SHA256:
        raise ValueError("Python archive does not match the python.org published SHA-256")
    wheel_paths = sorted(wheels.glob("*.whl"))
    if not wheel_paths:
        raise ValueError("Download the pinned wheels first")
    with ThreadPoolExecutor(max_workers=6) as pool:
        wheel_records = list(pool.map(verify_wheel, wheel_paths))
    expected = {line.strip().lower().replace("_", "-") for line in (ROOT / "requirements.lock.txt").read_text().splitlines()
                if line.strip() and not line.startswith("#")}
    actual = {(r["name"] + "==" + r["version"]).lower().replace("_", "-") for r in wheel_records}
    if actual != expected:
        raise ValueError("Wheel directory must match the complete pinned dependency set exactly")
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive_path) as archive:
        safe_extract(archive, target)
    site_packages = target / "Lib" / "site-packages"
    subprocess.run([sys.executable, "-m", "pip", "--isolated", "install", "--no-index", "--no-deps", "--no-compile",
                    "--no-warn-script-location", "--find-links", str(wheels), "--target", str(site_packages),
                    "-r", str(ROOT / "requirements.lock.txt")], check=True)
    # Explicit paths isolate this runtime from system Python and other virtual environments.
    (target / "python314._pth").write_text("python314.zip\n.\n..\nLib/site-packages\nimport site\n", encoding="utf-8")
    # pip console wrappers contain the build interpreter path. They are unnecessary:
    # all supported entry points use `runtime/python.exe -m ...` or a project script.
    for folder in (site_packages / "Scripts", site_packages / "bin"):
        if folder.exists():
            if not folder.resolve().is_relative_to(target.resolve()):
                raise ValueError("Unexpected script directory")
            shutil.rmtree(folder)
    for installed in site_packages.glob("*.dist-info/direct_url.json"):
        installed.unlink()  # local wheel-cache provenance is replaced with verified public URLs.
    write_json(target / "DEPENDENCIES.json", {"python": {"version": "3.14.4", "url": PYTHON_URL, "sha256": PYTHON_SHA256},
                                              "wheels": wheel_records})
    rows = []
    for path in sorted(target.rglob("*")):
        if path.is_file():
            rows.append({"path": path.relative_to(target).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size})
    write_json(target / "RUNTIME-MANIFEST.json", {"files": rows})
    print(json.dumps({"runtime_prepared": str(target), "dependencies": len(wheel_records), "files": len(rows)}))


def bundle(runtime, output):
    runtime, output = runtime.resolve(), output.resolve()
    if output.is_relative_to((ROOT / "web").resolve()) or output.is_relative_to(runtime):
        raise ValueError("Bundle output must be outside the web source and runtime directories")
    if output.exists():
        raise ValueError("Bundle output directory must not already exist")
    if not (ROOT / "web/dist/index.html").is_file():
        raise ValueError("Build the web interface before packaging")
    manifest = json.loads((runtime / "RUNTIME-MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest["files"]:
        path = (runtime / row["path"]).resolve()
        if not path.is_relative_to(runtime.resolve()) or digest(path) != row["sha256"]:
            raise ValueError("Runtime changed after preparation: " + row["path"])
    output.mkdir(parents=True)
    stage = output / NAME
    stage.mkdir()
    source_manifest = []
    for path in build_release.files(False):
        relative = path.relative_to(ROOT)
        data = build_release._public_bytes(path)
        dest = stage / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        source_manifest.append({"path": relative.as_posix(), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    write_json(stage / "source-manifest.json", {"version": "0.2.0", "files": source_manifest, "private_data_included": False})
    for path in (ROOT / "web/dist").rglob("*"):
        if path.is_file() and not path.is_symlink() and path.suffix in {".html", ".js", ".css", ".svg"}:
            dest = stage / path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(build_release._public_bytes(path))
    for row in manifest["files"]:
        dest = stage / "runtime" / row["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(runtime / row["path"], dest)
    shutil.copyfile(runtime / "RUNTIME-MANIFEST.json", stage / "runtime/RUNTIME-MANIFEST.json")
    deps = json.loads((runtime / "DEPENDENCIES.json").read_text(encoding="utf-8"))
    notices = ["# Third-party runtime notices", "", "Original project source: MIT (LICENSE).",
               "CPython 3.14.4: PSF license and included notices (runtime/LICENSE.txt).",
               "All Python package metadata and supplied license files are retained under runtime/Lib/site-packages.",
               "The project MIT license does not replace dependency licenses. NumPy/Shapely wheels retain bundled library notices.",
               "Python and wheel source URLs and SHA-256 values: runtime/DEPENDENCIES.json.", "", "| Package | Version | License metadata |", "|---|---|---|"]
    for row in deps["wheels"]:
        license_text = " ".join(str(row["license"]).split()).replace("|", "/")[:180]
        notices.append(f"| {row['name']} | {row['version']} | {license_text} |")
    (stage / "THIRD_PARTY_NOTICES.md").write_text("\n".join(notices) + "\n", encoding="utf-8")
    (stage / "先读我.txt").write_text(
        "清规AI · PlanningWorkbench Open 0.2.0\n\n"
        "适用：Windows 10/11 x64。请先完整解压到可写目录。\n"
        "双击“安装清规AI.cmd”检查运行环境并创建桌面快捷方式；双击“启动清规AI.cmd”打开工作台。\n"
        "本包已包含Python与依赖、道路/横断面/地块图则界面，不需另装Python、Node或.NET。\n"
        "本地计算和DXF导出无需模型API。CAD实时落图仍需用户自行安装可用AutoCAD；已验证环境见docs。\n"
        "确定性计算不是自动满足规范，默认示例不是大钟寺测绘数据。当前不等于商业控规软件全部功能。\n"
        "安装Codex技能：runtime\\python.exe install_skills.py；然后新开Codex会话。\n"
        "完整说明：README.md、docs/windows-portable.md、docs/mcp-usage.md。\n"
        "移动此目录后重新运行安装入口创建新的桌面入口；旧入口保留。\n"
        "技能需另行执行 install_skills.py --relocate-from 旧目录；会校验来源并备份。详见docs/windows-portable.md。\n", encoding="utf-8-sig")
    records = [{"path": p.relative_to(stage).as_posix(), "sha256": digest(p), "bytes": p.stat().st_size}
               for p in sorted(stage.rglob("*")) if p.is_file()]
    write_json(stage / "PORTABLE-MANIFEST.json", {"product": "清规AI · PlanningWorkbench Open 0.2.0", "platform": "windows-x64", "files": records})
    archive_path = output / (NAME + ".zip")
    with zipfile.ZipFile(archive_path, "x", zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                archive.write(p, NAME + "/" + p.relative_to(stage).as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Portable ZIP integrity failure")
    result = {"file": archive_path.name, "bytes": archive_path.stat().st_size, "sha256": digest(archive_path),
              "source_files": len(source_manifest), "runtime_files": len(manifest["files"]), "includes_cad": False}
    write_json(output / "portable-release.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-archive", type=Path)
    parser.add_argument("--wheels", type=Path)
    parser.add_argument("--runtime-out", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.runtime_out and args.python_archive and args.wheels and not (args.runtime or args.out):
        prepare_runtime(args.python_archive.resolve(), args.wheels.resolve(), args.runtime_out.resolve())
    elif args.runtime and args.out and not (args.runtime_out or args.python_archive or args.wheels):
        bundle(args.runtime.resolve(), args.out.resolve())
    else:
        parser.error("Use --python-archive --wheels --runtime-out, OR --runtime --out")


if __name__ == "__main__":
    main()
