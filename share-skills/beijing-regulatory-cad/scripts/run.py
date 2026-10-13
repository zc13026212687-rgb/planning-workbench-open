# qinggui-portable-wrapper: v2
"""Resolve the installed QingGui engine from local deployment metadata."""
import json
import os
import subprocess
import sys
from pathlib import Path

def main():
    metadata = Path(__file__).resolve().parents[1] / "local-engine.json"
    if not metadata.is_file():
        raise SystemExit("Skill is not deployed. Run the QingGui Starter installer first.")
    settings = json.loads(metadata.read_text(encoding="utf-8-sig"))
    root = Path(settings["root"])
    python = Path(settings["python"])
    cli = root / "planning_cli.py"
    if not python.is_file() or not cli.is_file():
        raise SystemExit("Installed engine is missing. Re-run the Starter installer or doctor.")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    return subprocess.call([str(python), "-B", str(cli), *sys.argv[1:]], env=env)

if __name__ == "__main__":
    sys.exit(main())
