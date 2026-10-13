import json
from pathlib import Path

from app.cases import get_case
from app.skills import diagnose_skill, list_skills, toggle_skill
from app.store import Store
from docs.run_teaching_examples import run

ROOT = Path(__file__).resolve().parents[1]


def test_imported_template_disabled_until_enabled_and_instructions_loaded(tmp_path):
    store = Store(tmp_path)
    try:
        item = next(x for x in list_skills(ROOT, store) if x["id"] == "road-review-template")
        assert item["ready"] is True
        assert item["enabled"] is False
        assert item["executor"] == "geometry"
        assert "calculate_roads" in item["instructions"]
        assert diagnose_skill(ROOT, store, item['id'])['status'] == 'passed'
        toggle_skill(ROOT, store, item['id'], True)
        assert next(x for x in list_skills(ROOT, store) if x["id"] == item["id"])["enabled"] is True
    finally:
        store.db.close()


def test_template_documented_contract_accepts_teaching_inputs():
    from jsonschema import Draft202012Validator
    schema = json.loads((ROOT / "skills/road-review-template/schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(get_case("regulatory-road-plan")["spec"])
    validator.validate(get_case("renewal-street-adjustment")["spec"])
    section_schema = json.loads((ROOT / "skills/road-cross-section/schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(section_schema)
    Draft202012Validator(section_schema).validate(get_case("road-cross-section")["spec"])


def test_tutorial_runner_keeps_failure_evidence_and_exports_only_valid_drawings(tmp_path):
    target = tmp_path / "teaching"
    results = run(target)
    assert results["regulatory-base"]["metrics"]["entity_count"] == 34
    assert results["renewal-A"]["errors"] == ["constraint_conflict"]
    assert not (target / "renewal-A.dxf").exists()
    assert (target / "renewal-A.result.json").exists()
    assert (target / "renewal-B.dxf").exists()
    assert results["cross-section"]["metrics"]["total_width"] == 24
    before = (target / "renewal-B.dxf").read_bytes()
    import pytest
    with pytest.raises(FileExistsError):
        run(target)
    assert (target / "renewal-B.dxf").read_bytes() == before
