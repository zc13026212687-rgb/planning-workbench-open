"""Install all five QingGui skills as one recoverable local transaction.

Only the installer-generated local-engine.json contains machine-local paths.
No CAD, network, client configuration, credentials, or model APIs are touched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

VERSION = "0.3.1"
INSTALLER = "qinggui-starter"
NAMES = (
    "qinggui-cad-workflow",
    "beijing-regulatory-cad",
    "planning-cad-road-plan",
    "planning-cad-cross-section",
    "planning-cad-regulatory-suite",
)


def absolute(path):
    # Do not resolve redirects before inspecting them.
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def plain_ancestors(path):
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError(f"Refusing a symbolic link or junction: {item}")


def plain_tree(path):
    plain_ancestors(path)
    for item in path.rglob("*"):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError(f"Refusing a symbolic link or junction: {item}")
        if not item.is_file() and not item.is_dir():
            raise ValueError(f"Unsupported filesystem object: {item}")


def tree_hashes(path):
    return {item.relative_to(path).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
            for item in sorted(path.rglob("*")) if item.is_file()}


def write_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def managed_target(path, name):
    if not path.is_dir():
        raise ValueError(f"Existing skill is not a directory: {name}")
    plain_tree(path)
    try:
        meta = json.loads((path / "local-engine.json").read_text(encoding="utf-8-sig"))
        doc = (path / "SKILL.md").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        script = (path / "scripts" / "run.py").read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as exc:
        raise ValueError(f"Existing skill is not managed by QingGui; unchanged: {name}") from exc
    old = meta.get("installer") == "planning-workbench" and meta.get("wrapper_schema") == 1
    current = meta.get("installer") == INSTALLER and meta.get("wrapper_schema") == 2
    if (meta.get("skill") != name or f"name: {name}\n" not in doc
            or not ((old and "# planning-workbench-wrapper: v1" in script)
                    or (current and "# qinggui-portable-wrapper: v2" in script))):
        raise ValueError(f"Existing skill has no recognized ownership marker; unchanged: {name}")


def preflight(source, destination, engine, interpreter):
    source, destination, engine, interpreter = map(absolute, (source, destination, engine, interpreter))
    for path in (source, destination, engine, interpreter):
        plain_ancestors(path)
    if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Source and destination skill directories must not overlap")
    if not interpreter.is_file() or not (engine / "planning_cli.py").is_file():
        raise ValueError("The selected installed engine or Python interpreter is missing")
    sources, before = {}, {}
    # Preflight every target before creating a transaction or modifying a skill.
    for name in NAMES:
        folder = source / name
        if not folder.is_dir():
            raise ValueError(f"Missing complete skill source: {name}")
        plain_tree(folder)
        doc = (folder / "SKILL.md").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        wrapper = (folder / "scripts" / "run.py").read_text(encoding="utf-8-sig")
        if f"name: {name}\n" not in doc or "# qinggui-portable-wrapper: v2" not in wrapper:
            raise ValueError(f"Skill name or portable wrapper does not match: {name}")
        if (folder / "local-engine.json").exists():
            raise ValueError(f"Release source contains machine-local metadata: {name}")
        sources[name] = tree_hashes(folder)
        target = destination / name
        if target.exists() or target.is_symlink():
            managed_target(target, name)
            before[name] = tree_hashes(target)
        else:
            before[name] = None
    return source, destination, engine, interpreter, sources, before


def install(source, destination, engine, interpreter, *, preflight_only=False):
    source, destination, engine, interpreter, sources, before = preflight(source, destination, engine, interpreter)
    if preflight_only:
        return {"status": "preflight_passed", "skills": list(NAMES), "destination": str(destination)}
    expected = {}
    metadata = {"root": str(engine), "python": str(interpreter), "version": VERSION,
                "installer": INSTALLER, "wrapper_schema": 2}
    for name in NAMES:
        blob = json.dumps({**metadata, "skill": name}, ensure_ascii=False, indent=2).encode("utf-8")
        expected[name] = {**sources[name], "local-engine.json": hashlib.sha256(blob).hexdigest()}
    if all(before[name] == expected[name] for name in NAMES):
        return {"status": "already_current", "version": VERSION, "skills": list(NAMES),
                "destination": str(destination), "engine": str(engine)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ-") + uuid.uuid4().hex[:8]
    transactions = destination.parent / "qinggui-skill-backups"
    plain_ancestors(transactions)
    transaction = transactions / run_id
    transaction.mkdir(parents=True, exist_ok=False)
    stage, backup, displaced = transaction / "stage", transaction / "before", transaction / "displaced"
    stage.mkdir()
    backup.mkdir()
    displaced.mkdir()
    record = {"installer": INSTALLER, "version": VERSION, "status": "preparing",
              "destination": str(destination), "engine": str(engine), "skills": list(NAMES),
              "before_hashes": before, "after_hashes": expected}
    record_path = transaction / "transaction.json"
    write_json(record_path, record)
    activated, moved = [], []
    try:
        for name in NAMES:
            shutil.copytree(source / name, stage / name)
            if tree_hashes(stage / name) != sources[name]:
                raise ValueError(f"Source changed while staging: {name}")
            write_json(stage / name / "local-engine.json", {**metadata, "skill": name})
            if tree_hashes(stage / name) != expected[name]:
                raise ValueError(f"Staged content failed verification: {name}")
            if before[name] is not None:
                shutil.copytree(destination / name, backup / name)
                if tree_hashes(backup / name) != before[name]:
                    raise ValueError(f"Full backup failed verification: {name}")
        # Re-check all targets before the first mutation, including concurrent writes.
        plain_ancestors(destination)
        for name in NAMES:
            target = destination / name
            if before[name] is None:
                if target.exists() or target.is_symlink():
                    raise ValueError(f"Target appeared during preflight: {name}")
            else:
                plain_tree(target)
                if tree_hashes(target) != before[name]:
                    raise ValueError(f"Target changed during preflight: {name}")
        record["status"] = "activating"
        write_json(record_path, record)
        destination.mkdir(exist_ok=True)
        for name in NAMES:
            target = destination / name
            if before[name] is not None:
                os.replace(target, displaced / name)
                moved.append(name)
            os.replace(stage / name, target)
            activated.append(name)
        for name in NAMES:
            if tree_hashes(destination / name) != expected[name]:
                raise ValueError(f"Installed skill failed verification: {name}")
        record["status"] = "installed"
        write_json(record_path, record)
    except Exception as exc:
        failures = []
        # Restore entire directories, preserving extra reference/assets/custom files.
        for name in reversed(NAMES):
            try:
                target = destination / name
                if name in activated:
                    failed = transaction / ("failed-" + name)
                    os.replace(target, failed)
                if name in moved:
                    os.replace(displaced / name, target)
                if before[name] is not None and name in moved and tree_hashes(target) != before[name]:
                    raise ValueError("Restored hashes differ")
            except Exception as rollback_exc:
                failures.append({"skill": name, "error": str(rollback_exc)})
        record.update(status="rollback_failed" if failures else "rolled_back", error=str(exc), rollback_errors=failures)
        write_json(record_path, record)
        if failures:
            raise RuntimeError(f"Restore required from verified backups at {transaction}") from exc
        raise
    return {"status": "installed", "version": VERSION, "skills": list(NAMES),
            "destination": str(destination), "engine": str(engine), "backup": str(transaction),
            "receipt": str(record_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    result = install(args.source, args.dest, args.engine, args.python, preflight_only=args.preflight_only)
    if args.receipt:
        plain_ancestors(absolute(args.receipt))
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.receipt, result)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
