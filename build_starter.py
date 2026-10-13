"""Build the public Starter, portable skills and source archives from allowlists."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import build_release

ROOT = Path(__file__).resolve().parent
VERSION = "0.3.1"
SETUP_NAME = "QingGuiAI-CAD-0.3.0-Setup.exe"
SETUP_SHA256 = "964a7f192da324c7c1d688dbec2511aac11b34f247a07b64c3e44bd9297ce365"
FOLDERS = {
    "share-skills": {".md", ".json", ".py", ".yaml"},
    "deploy": {".py", ".ps1", ".md", ".json"},
    "cad-native": {".md", ".py", ".cs", ".csproj", ".ps1", ".json", ".xml", ".scr", ".txt", ".manifest", ".ico"},
}
ROOT_NAMES = {"build_starter.py", "Install-Codex.cmd", "Install-Claude.cmd", "Install-OpenClaw.cmd"}


def public_files():
    paths = set(build_release.files(False))
    for folder, suffixes in FOLDERS.items():
        paths.update(p for p in (ROOT / folder).rglob("*")
                     if (p.suffix.lower() in suffixes or p.name == "LICENSE") and build_release._allowed(p))
    paths.update(ROOT / name for name in ROOT_NAMES)
    contents = {}
    for path in sorted(paths):
        name = path.relative_to(ROOT).as_posix()
        if name == "cad-native/launcher/QingGuiAI.ico":
            # Original generated icon, the only allowed binary source asset.
            data = path.read_bytes()
            if data[:4] != b"\x00\x00\x01\x00":
                raise ValueError("Expected original Windows icon source")
            contents[name] = data
        else:
            contents[name] = build_release._public_bytes(path)
    required = {"cad-native/installer/app.manifest", "cad-native/launcher/QingGuiAI.ico",
                "cad-native/native/QingGuiAI.Cad.csproj", "deploy/Install.ps1"}
    if not required.issubset(contents):
        raise ValueError("Release missing required native/deployment source: " + str(required - contents.keys()))
    return contents


def write_archive(path, prefix, contents):
    manifest = [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in sorted(contents.items())]
    all_entries = dict(contents)
    all_entries["package-manifest.json"] = json.dumps({
        "product": "QingGuiAI Starter", "starter_version": VERSION, "native_version": "0.3.0",
        "engine_version": "0.2.0", "files": manifest,
        "private_course_data_included": False,
    }, ensure_ascii=False, indent=2).encode("utf-8")
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(all_entries.items()):
            entry = zipfile.ZipInfo(prefix + "/" + name, date_time=(2026, 10, 13, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    with zipfile.ZipFile(path) as archive:
        if archive.testzip():
            raise ValueError("Archive failed CRC verification")
        for row in manifest:
            if hashlib.sha256(archive.read(prefix + "/" + row["path"])).hexdigest() != row["sha256"]:
                raise ValueError("Archive manifest mismatch")
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "files": len(manifest)}


def build(setup, out):
    setup = Path(setup)
    blob = setup.read_bytes()
    if hashlib.sha256(blob).hexdigest() != SETUP_SHA256:
        raise ValueError("Only the pinned, tested native 0.3.0 installer can enter this release")
    source = public_files()
    skills = {name: data for name, data in source.items()
              if name.startswith(("share-skills/", "deploy/", "docs/")) or name in ROOT_NAMES - {"build_starter.py"}
              or name in {"LICENSE", "README.md", "cad-native/README.md", "cad-native/THIRD_PARTY_NOTICES.md"}}
    skills["README.md"] = """# 清规AI 0.3.1 技能包

本包有五个完整技能和部署脚本，适合已经安装清规AI原生引擎的使用者。
本包不含计算引擎/Python运行时，不能只复制SKILL.md后声称完成CAD接入。

首次使用请下载 [完整Starter](https://github.com/zc13026212687-rgb/planning-workbench-open/releases/tag/v0.3.1)。
已安装本版原生bundle时可运行对应 Install-Codex.cmd / Install-Claude.cmd / Install-OpenClaw.cmd；
部署器确认已有bundle并跳过重装，然后安装技能并运行本地诊断。
自定义引擎需要 runtime/python.exe，并使用 -SkipCadInstall -EnginePath 指向它。

操作、目录、客户端范围和回执解释见 [安装说明](docs/starter-installation.md)。
首次练习见 [quickstart](share-skills/qinggui-cad-workflow/references/quickstart.md)。
完整源码与构建文档见 [仓库](https://github.com/zc13026212687-rgb/planning-workbench-open)。
原创技能与部署脚本采用 [MIT](LICENSE)，本包不包含私人课程数据或第三方专有软件。
""".encode("utf-8")
    starter = dict(source)
    starter["payload/" + SETUP_NAME] = blob
    packages = [
        (f"QingGuiAI-Starter-{VERSION}-windows-x64", starter),
        (f"QingGuiAI-{VERSION}-source", source),
        (f"QingGuiAI-{VERSION}-skills", skills),
    ]
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name, _ in packages:
        if (out / (name + ".zip")).exists():
            raise FileExistsError("Choose a fresh output directory; release files are never overwritten")
    records = [write_archive(out / (name + ".zip"), name, contents) for name, contents in packages]
    (out / "SHA256SUMS.txt").write_text("".join(f"{r['sha256']}  {r['file']}\n" for r in records), encoding="ascii")
    (out / "release-manifest.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-installer", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.native_installer, args.out), indent=2))
