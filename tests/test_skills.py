import copy
import json
from pathlib import Path

import pytest

from app.cases import get_case
from app.skills import diagnose_skill, list_skills, toggle_skill, validate_skill_input
from app.store import Store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def registry(tmp_path):
    root = tmp_path / 'project'
    folder = root / 'skills' / 'teacher-road'
    folder.mkdir(parents=True)
    manifest = {'id': 'teacher-road', 'name': '教学试运行', 'executor': 'geometry',
                'permissions': ['project:read', 'artifact:write'], 'input_schema': 'schema.json'}
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object',
              'required': ['left_width'], 'properties': {'left_width': {'type': 'number', 'minimum': 8}}}
    (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (folder / 'SKILL.md').write_text('教师试运行，仅用注册几何引擎。', encoding='utf-8')
    (folder / 'schema.json').write_text(json.dumps(schema), encoding='utf-8')
    store = Store(tmp_path / 'data')
    yield root, folder, store
    store.db.close()


def item(root, store):
    return next(s for s in list_skills(root, store) if s['id'] == 'teacher-road')


def update_json(path, **changes):
    data = json.loads(path.read_text(encoding='utf-8'))
    data.update(changes)
    path.write_text(json.dumps(data), encoding='utf-8')


def test_local_enable_requires_real_geometry_diagnostic_and_input_contract(registry):
    root, folder, store = registry
    with pytest.raises(ValueError, match='诊断'):
        toggle_skill(root, store, 'teacher-road', True)
    # Old arbitrary registry state cannot bypass current-content diagnostics.
    store.put('skill_states', {'id': 'teacher-road', 'enabled': True})
    assert not item(root, store)['enabled']
    result = diagnose_skill(root, store, 'teacher-road')
    assert result['status'] == 'passed'
    assert result['entity_count'] == 34
    assert result['metrics']['junction_count'] == 2
    assert not (store.folder / 'artifacts').exists()
    assert store.list('jobs') == [] and store.list('cad_audit') == []
    assert not item(root, store)['enabled']
    enabled = toggle_skill(root, store, 'teacher-road', True)
    assert enabled['enabled'] and enabled['schema_definition']
    spec = get_case('regulatory-road-plan')['spec']
    validate_skill_input(enabled, spec)
    changed = copy.deepcopy(spec)
    changed['left_width'] = 7  # Valid engine geometry, invalid teacher contract.
    with pytest.raises(ValueError, match='left_width'):
        validate_skill_input(enabled, changed)


@pytest.mark.parametrize('filename', ['SKILL.md', 'schema.json', 'manifest.json'])
def test_file_changes_revoke_diagnostic_and_require_explicit_reenable(registry, filename):
    root, folder, store = registry
    first = diagnose_skill(root, store, 'teacher-road')
    toggle_skill(root, store, 'teacher-road', True)
    path = folder / filename
    if filename == 'SKILL.md':
        path.write_text(path.read_text(encoding='utf-8') + '\n说明修订', encoding='utf-8')
    else:
        update_json(path, description='新版本')
    current = item(root, store)
    assert current['content_hash'] != first['content_hash']
    assert current['validation_state'] == 'stale' and not current['enabled']
    with pytest.raises(ValueError):
        toggle_skill(root, store, 'teacher-road', True)
    assert diagnose_skill(root, store, 'teacher-road')['status'] == 'passed'
    assert not item(root, store)['enabled']
    assert toggle_skill(root, store, 'teacher-road', True)['enabled']


def test_schema_path_cannot_read_outside_skill_folder(registry):
    root, folder, store = registry
    secret = folder.parent / 'outside.json'
    secret.write_text('{"description":"NEVER-READ-OUTSIDE"}', encoding='utf-8')
    update_json(folder / 'manifest.json', input_schema='../outside.json')
    skill = item(root, store)
    assert not skill['ready'] and skill['schema_definition'] is None
    assert 'NEVER-READ-OUTSIDE' not in json.dumps(skill)
    assert diagnose_skill(root, store, 'teacher-road')['status'] == 'failed'


@pytest.mark.parametrize('ref', ['https://example.invalid/schema.json', 'file:///private.json', 'other.json#/properties/x'])
def test_external_refs_fail_without_any_retrieval(registry, monkeypatch, ref):
    root, folder, store = registry
    called = []
    monkeypatch.setattr('app.skills._blocked_retrieval', lambda uri: called.append(uri))
    update_json(folder / 'schema.json', **{'$ref': ref})
    skill = item(root, store)
    assert not skill['ready']
    result = diagnose_skill(root, store, 'teacher-road')
    assert result['status'] == 'failed' and result['entity_count'] == 0
    assert not called


def test_internal_reference_is_enforced_and_bad_schema_stays_visible(registry):
    root, folder, store = registry
    update_json(folder / 'schema.json', properties={'left_width': {'$ref': '#/$defs/width'}},
                **{'$defs': {'width': {'type': 'number', 'minimum': 8}}})
    assert diagnose_skill(root, store, 'teacher-road')['status'] == 'passed'
    enabled = toggle_skill(root, store, 'teacher-road', True)
    with pytest.raises(ValueError, match='left_width'):
        validate_skill_input(enabled, {'left_width': 1})
    update_json(folder / 'schema.json', type='invented-type')
    skill = item(root, store)
    assert skill['validation_state'] == 'invalid' and not skill['enabled']
    assert skill['validation_errors']


def test_dependencies_exist_and_changes_invalidate(registry):
    root, folder, store = registry
    update_json(folder / 'manifest.json', dependencies=['references/teacher.json'])
    assert not item(root, store)['ready']
    assert diagnose_skill(root, store, 'teacher-road')['status'] == 'failed'
    (folder / 'references').mkdir()
    resource = folder / 'references/teacher.json'
    resource.write_text('{"lesson":"A"}', encoding='utf-8')
    assert diagnose_skill(root, store, 'teacher-road')['status'] == 'passed'
    toggle_skill(root, store, 'teacher-road', True)
    resource.write_text('{"lesson":"B"}', encoding='utf-8')
    assert item(root, store)['validation_state'] == 'stale'
    assert not item(root, store)['enabled']


@pytest.mark.parametrize('changes', [
    {'executor': 'python'}, {'permissions': ['project:read', 'shell:execute']},
    {'permissions': ['project:read']}, {'dependencies': ['../../outside.py']},
])
def test_unregistered_executors_and_permissions_never_authorize(registry, changes):
    root, folder, store = registry
    update_json(folder / 'manifest.json', **changes)
    assert not item(root, store)['ready']
    assert diagnose_skill(root, store, 'teacher-road')['status'] == 'failed'
    with pytest.raises(ValueError):
        toggle_skill(root, store, 'teacher-road', True)


def test_diagnostic_failure_does_not_enable_or_claim_geometry_success(registry):
    root, folder, store = registry
    update_json(folder / 'schema.json', properties={'left_width': {'minimum': 1000}})
    result = diagnose_skill(root, store, 'teacher-road')
    assert result['status'] == 'failed' and result['success'] is False
    assert result['errors'] and result['entity_count'] == 0
    assert item(root, store)['validation_state'] == 'failed'
    with pytest.raises(ValueError):
        toggle_skill(root, store, 'teacher-road', True)


def test_builtin_section_diagnostic_runs_real_section_and_checks_its_schema(tmp_path):
    store = Store(tmp_path)
    try:
        result = diagnose_skill(ROOT, store, 'road-cross-section')
        assert result['status'] == 'passed' and result['entity_count'] == 39
        assert result['metrics']['total_width'] == 24
        section = next(s for s in list_skills(ROOT, store) if s['id'] == 'road-cross-section')
        spec = get_case('road-cross-section')['spec']
        validate_skill_input(section, spec)
        spec['components'][0]['curb_height'] = 0.15
        with pytest.raises(ValueError, match='Schema'):
            validate_skill_input(section, spec)
        assert 'resource_locks' not in section
        assert diagnose_skill(ROOT, store, 'inspect-project')['status'] == 'failed'
    finally:
        store.db.close()
