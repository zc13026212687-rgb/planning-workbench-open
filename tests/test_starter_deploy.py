"""Isolated installer tests; never writes a real skill/client/CAD installation."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("starter_skills", ROOT / "deploy" / "install_portable_skills.py")
starter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(starter)


@pytest.fixture
def package(tmp_path):
    source, dest, engine = tmp_path / "share-skills", tmp_path / "client" / "skills", tmp_path / "engine"
    engine.mkdir()
    (engine / "planning_cli.py").write_text("print('[]')", encoding="utf-8")
    for name in starter.NAMES:
        directory = source / name
        (directory / "scripts").mkdir(parents=True)
        (directory / "references").mkdir()
        (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test skill\n---\n", encoding="utf-8")
        (directory / "scripts" / "run.py").write_text("# qinggui-portable-wrapper: v2\n", encoding="utf-8")
        (directory / "references" / "guide.md").write_text("Complete portable reference", encoding="utf-8")
    return source, dest, engine, Path(sys.executable)


def test_first_install_copies_complete_skills_and_is_idempotent(package):
    source, dest, engine, interpreter = package
    result = starter.install(*package)
    assert result["status"] == "installed"
    for name in starter.NAMES:
        assert (dest / name / "references" / "guide.md").read_bytes() == (source / name / "references" / "guide.md").read_bytes()
        meta = json.loads((dest / name / "local-engine.json").read_text(encoding="utf-8"))
        assert meta["root"] == str(engine)
        assert meta["python"] == str(interpreter)
        assert meta["installer"] == "qinggui-starter"
        assert meta["skill"] == name
    assert starter.install(*package)["status"] == "already_current"


def test_unowned_last_target_prevents_every_skill_write(package):
    source, dest, _, _ = package
    conflict = dest / starter.NAMES[-1]
    conflict.mkdir(parents=True)
    (conflict / "SKILL.md").write_text("User-owned unrelated skill", encoding="utf-8")
    before = starter.tree_hashes(dest)
    with pytest.raises(ValueError, match="not managed"):
        starter.install(*package)
    assert starter.tree_hashes(dest) == before
    assert not (dest.parent / "qinggui-skill-backups").exists()


def test_legacy_wrapper_migration_preserves_complete_backup(package):
    _, dest, _, _ = package
    legacy = dest / starter.NAMES[0]
    (legacy / "scripts").mkdir(parents=True)
    (legacy / "my-extra-notes").mkdir()
    (legacy / "my-extra-notes" / "custom.txt").write_text("Do not lose manual edits", encoding="utf-8")
    (legacy / "SKILL.md").write_text(f"---\nname: {starter.NAMES[0]}\n---\nManual notes", encoding="utf-8")
    (legacy / "scripts" / "run.py").write_text("# planning-workbench-wrapper: v1\n", encoding="utf-8")
    (legacy / "local-engine.json").write_text(json.dumps({"installer": "planning-workbench", "wrapper_schema": 1, "skill": starter.NAMES[0]}), encoding="utf-8")
    before = starter.tree_hashes(legacy)
    result = starter.install(*package)
    backup = Path(result["backup"]) / "before" / starter.NAMES[0]
    assert starter.tree_hashes(backup) == before


def test_mid_activation_failure_rolls_back_all_original_directories(package, monkeypatch):
    starter.install(*package)
    source, dest, _, _ = package
    for name in starter.NAMES:
        (dest / name / "preserved-user-note.txt").write_text(name, encoding="utf-8")
        (source / name / "references" / "guide.md").write_text("new source", encoding="utf-8")
    before = starter.tree_hashes(dest)
    replace = starter.os.replace
    def fail_third_skill(src, target):
        if Path(src).parent.name == "stage" and Path(src).name == starter.NAMES[2]:
            raise OSError("simulated locked skill")
        return replace(src, target)
    monkeypatch.setattr(starter.os, "replace", fail_third_skill)
    with pytest.raises(OSError, match="locked skill"):
        starter.install(*package)
    assert starter.tree_hashes(dest) == before
    records = list((dest.parent / "qinggui-skill-backups").glob("*/transaction.json"))
    assert any(json.loads(row.read_text(encoding="utf-8"))["status"] == "rolled_back" for row in records)


def test_failed_first_install_leaves_no_partial_skills(package, monkeypatch):
    _, dest, _, _ = package
    replace = starter.os.replace
    def fail_third_skill(src, target):
        if Path(src).parent.name == "stage" and Path(src).name == starter.NAMES[2]:
            raise OSError("simulated initial failure")
        return replace(src, target)
    monkeypatch.setattr(starter.os, "replace", fail_third_skill)
    with pytest.raises(OSError, match="initial failure"):
        starter.install(*package)
    assert not any((dest / name).exists() for name in starter.NAMES)


def test_release_local_paths_are_rejected_before_install(package):
    source, dest, _, _ = package
    (source / starter.NAMES[-1] / "local-engine.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="machine-local"):
        starter.install(*package)
    assert not dest.exists()


def test_symlink_in_source_rejected(package, tmp_path):
    source, dest, _, _ = package
    try:
        (source / starter.NAMES[-1] / "redirect").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation unavailable to this account")
    with pytest.raises(ValueError, match="symbolic link"):
        starter.install(*package)
    assert not dest.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction")
def test_junction_target_rejected_without_touching_outside(package, tmp_path):
    _, dest, _, _ = package
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    dest.parent.mkdir()
    result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(dest), str(outside)], capture_output=True)
    if result.returncode:
        pytest.skip("Junction creation unavailable")
    try:
        with pytest.raises(ValueError, match="junction"):
            starter.install(*package)
        assert list(outside.iterdir()) == [outside / "keep.txt"]
    finally:
        dest.rmdir()  # Remove only this explicitly created test junction, never its target.


def test_preflight_only_does_not_create_destination(package):
    assert starter.install(*package, preflight_only=True)["status"] == "preflight_passed"
    assert not package[1].exists()


@pytest.mark.skipif(os.name != "nt", reason="PowerShell parser")
def test_powershell_install_script_parses():
    script = str(ROOT / "deploy" / "Install.ps1").replace("'", "''")
    command = "$errors = $null; $tokens = $null; [System.Management.Automation.Language.Parser]::ParseFile('" + script + "',[ref]$tokens,[ref]$errors) | Out-Null; if ($errors.Count) { $errors | ForEach-Object { $_.Message }; exit 1 }"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows installed local engine")
def test_complete_powershell_pipeline_isolated_with_real_engine(package, tmp_path):
    engine = Path(os.environ["APPDATA"]) / "Autodesk/ApplicationPlugins/QingGuiAI.bundle/Contents/Engine"
    if not (engine / "runtime/python.exe").is_file():
        pytest.skip("Optional installed QingGui engine integration test")
    source, dest, _, _ = package
    deploy = source.parent / "deploy"
    shutil.copytree(ROOT / "deploy", deploy)
    receipts = tmp_path / "receipts"
    args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(deploy / "Install.ps1"),
            "-Client", "codex", "-SkillsDirectory", str(dest), "-SkipCadInstall", "-EnginePath", str(engine),
            "-SkipMcpRegistration", "-ReceiptDirectory", str(receipts)]
    run = subprocess.run(args, capture_output=True, timeout=90)
    assert run.returncode == 0, run.stdout.decode("utf-8", "replace") + run.stderr.decode("utf-8", "replace")
    report = json.loads(next(receipts.glob("*/deployment.json")).read_text(encoding="utf-8-sig"))
    assert report["doctor"]["status"] == "passed"
    assert report["skills"]["status"] == "installed"
    assert report["status"] == "skills_ready_mcp_registration_skipped"
    again = subprocess.run(args, capture_output=True, timeout=90)
    assert again.returncode == 0
    results = [json.loads(path.read_text(encoding="utf-8-sig")) for path in receipts.glob("*/deployment.json")]
    assert any(item["skills"]["status"] == "already_current" for item in results)


@pytest.mark.skipif(os.name != "nt", reason="Windows installed Codex CLI")
def test_codex_registration_uses_official_cli_with_isolated_config(package, tmp_path):
    engine = Path(os.environ["APPDATA"]) / "Autodesk/ApplicationPlugins/QingGuiAI.bundle/Contents/Engine"
    if not (engine / "runtime/python.exe").is_file() or not shutil.which("codex.cmd"):
        pytest.skip("Optional installed engine and Codex CLI integration test")
    source, dest, _, _ = package
    deploy = source.parent / "deploy"
    shutil.copytree(ROOT / "deploy", deploy)
    codex_home = tmp_path / "isolated-codex-home"
    codex_home.mkdir()
    environment = {**os.environ, "CODEX_HOME": str(codex_home)}
    receipts = tmp_path / "receipts"
    args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(deploy / "Install.ps1"),
            "-Client", "codex", "-SkillsDirectory", str(dest), "-SkipCadInstall", "-EnginePath", str(engine),
            "-ReceiptDirectory", str(receipts)]
    result = subprocess.run(args, capture_output=True, timeout=90, env=environment)
    assert result.returncode == 0, result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace")
    reports = [json.loads(row.read_text(encoding="utf-8-sig")) for row in receipts.glob("*/deployment.json")]
    assert reports[0]["mcp"]["status"] == "registered"
    before = (codex_home / "config.toml").read_bytes()
    result = subprocess.run(args, capture_output=True, timeout=90, env=environment)
    assert result.returncode == 0
    assert (codex_home / "config.toml").read_bytes() == before
    reports = [json.loads(row.read_text(encoding="utf-8-sig")) for row in receipts.glob("*/deployment.json")]
    assert any(row["mcp"]["status"] == "already_registered" for row in reports)


@pytest.mark.skipif(os.name != "nt", reason="Windows installed Codex CLI")
def test_codex_conflict_is_preserved_with_needs_registration(package, tmp_path):
    engine = Path(os.environ["APPDATA"]) / "Autodesk/ApplicationPlugins/QingGuiAI.bundle/Contents/Engine"
    if not (engine / "runtime/python.exe").is_file() or not shutil.which("codex.cmd"):
        pytest.skip("Optional installed engine and Codex CLI integration test")
    source, dest, _, _ = package
    deploy = source.parent / "deploy"
    shutil.copytree(ROOT / "deploy", deploy)
    codex_home = tmp_path / "isolated-codex-home"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    config.write_bytes(b'[mcp_servers.qinggui-cad]\ncommand = "some-unrelated-server.exe"\nargs = []\n')
    before = config.read_bytes()
    receipts = tmp_path / "receipts"
    args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(deploy / "Install.ps1"),
            "-Client", "codex", "-SkillsDirectory", str(dest), "-SkipCadInstall", "-EnginePath", str(engine),
            "-ReceiptDirectory", str(receipts)]
    result = subprocess.run(args, capture_output=True, timeout=90, env={**os.environ, "CODEX_HOME": str(codex_home)})
    assert result.returncode == 2, result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace")
    report = json.loads(next(receipts.glob("*/deployment.json")).read_text(encoding="utf-8-sig"))
    assert report["mcp"]["status"] == "name_conflict_unchanged"
    assert config.read_bytes() == before
