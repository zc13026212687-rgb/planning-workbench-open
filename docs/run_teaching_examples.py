"""Run with .venv/Scripts/python.exe -m docs.run_teaching_examples --output NEW_DIR.

Creates original synthetic examples/reports only. Never opens CAD or calls APIs.
"""
import argparse
import json
from pathlib import Path

from app.cases import get_case
from app.geometry import export_dxf, generate
from app.sections import export_section_dxf, generate as generate_section


def run(output: Path):
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    regulatory = get_case("regulatory-road-plan")["spec"]
    renewal = get_case("renewal-street-adjustment")
    cases = [("regulatory-base", regulatory, generate, export_dxf)]
    for variant in renewal["variants"]:
        cases.append(("renewal-" + variant["id"], variant["spec"], generate, export_dxf))
    cases.append(("cross-section", get_case("road-cross-section")["spec"], generate_section, export_section_dxf))
    for name, spec, calculate, export in cases:
        result = calculate(spec)
        (output / f"{name}.parameters.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / f"{name}.result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if not result["report"]["errors"]:
            export(result, output / f"{name}.dxf")
        results[name] = {"errors": [e["code"] for e in result["report"]["errors"]], "metrics": result["metrics"]}
    (output / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="新输出目录；存在则拒绝覆盖")
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, indent=2))
