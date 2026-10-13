"""Skill migration uses temporary destinations only, never real user skills."""
import json
from pathlib import Path
import sys

import pytest

import install_skills as installer


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob('*') if p.is_file()}


@pytest.fixture
def installed(tmp_path, monkeypatch):
    old, new, dest = tmp_path / 'old engine', tmp_path / 'new engine', tmp_path / 'skills'
    for root in (old, new):
        for source, _, _ in installer.SKILLS:
            folder = root / 'skills' / source
            folder.mkdir(parents=True)
            (folder / 'SKILL.md').write_text('Original engine fixture', encoding='utf-8')
    monkeypatch.setattr(installer, 'ROOT', old)
    installer.main(['--dest', str(dest), '--python', sys.executable])
    monkeypatch.setattr(installer, 'ROOT', new)
    return old, new, dest


def args(old, dest):
    return ['--dest', str(dest), '--python', sys.executable, '--relocate-from', str(old)]


def test_explicit_migration_backs_up_all_four_and_preserves_other_content(installed):
    old, new, dest = installed
    note = dest / 'planning-cad-road-plan' / 'personal-note.md'
    note.write_text('keep this note', encoding='utf-8')
    unrelated = dest / 'unrelated-skill'
    unrelated.mkdir()
    (unrelated / 'SKILL.md').write_text('keep other skill', encoding='utf-8')
    before = snapshot(dest)
    assert installer.main(args(old, dest)) == 0
    backups = list((dest.parent / 'planning-workbench-skill-backups').iterdir())
    assert len(backups) == 1
    backup = backups[0]
    record = json.loads((backup / 'migration.json').read_text(encoding='utf-8'))
    assert record['status'] == 'succeeded'
    assert len(record['skills']) == 4
    for _, name, _ in installer.SKILLS:
        prior = {key[len(name) + 1:]: value for key, value in before.items() if key.startswith(name + '/')}
        assert snapshot(backup / name) == prior
        metadata = json.loads((dest / name / 'local-engine.json').read_text(encoding='utf-8'))
        assert metadata['root'] == str(new) and metadata['python'] == str(Path(sys.executable).resolve())
        assert metadata['installer'] == 'planning-workbench'
    assert note.read_text(encoding='utf-8') == 'keep this note'
    assert snapshot(unrelated) == {'SKILL.md': b'keep other skill'}


def test_migration_old_location_need_not_still_exist(installed):
    old, new, dest = installed
    old.rename(old.with_name('old moved away'))
    assert not old.exists()
    assert installer.main(args(old, dest)) == 0


def test_no_flag_still_refuses_other_root_and_writes_nothing(installed):
    old, new, dest = installed
    before = snapshot(dest.parent)
    with pytest.raises(ValueError, match='引擎路径不符'):
        installer.main(['--dest', str(dest), '--python', sys.executable])
    assert snapshot(dest.parent) == before


def test_last_target_wrong_root_rejected_before_any_backup_or_write(installed):
    old, new, dest = installed
    path = dest / installer.SKILLS[-1][1] / 'local-engine.json'
    metadata = json.loads(path.read_text(encoding='utf-8'))
    metadata['root'] = str(old / 'unrelated')
    path.write_text(json.dumps(metadata), encoding='utf-8')
    before = snapshot(dest.parent)
    with pytest.raises(ValueError, match='引擎路径不符'):
        installer.main(args(old, dest))
    assert snapshot(dest.parent) == before
    assert not (dest.parent / 'planning-workbench-skill-backups').exists()


@pytest.mark.parametrize('change', ['wrapper', 'skill_name', 'metadata_skill'])
def test_unrecognized_or_modified_wrapper_is_not_claimed(installed, change):
    old, new, dest = installed
    target = dest / installer.SKILLS[-1][1]
    if change == 'wrapper':
        with (target / 'scripts/run.py').open('a', encoding='utf-8') as handle:
            handle.write('\nprint("custom code")\n')
    elif change == 'skill_name':
        (target / 'SKILL.md').write_text('name: unrelated\n', encoding='utf-8')
    else:
        path = target / 'local-engine.json'
        metadata = json.loads(path.read_text(encoding='utf-8'))
        metadata['skill'] = 'unrelated'
        path.write_text(json.dumps(metadata), encoding='utf-8')
    before = snapshot(dest.parent)
    with pytest.raises(ValueError, match='来源标记'):
        installer.main(args(old, dest))
    assert snapshot(dest.parent) == before


def test_known_legacy_template_can_be_migrated(installed):
    old, new, dest = installed
    for _, name, _ in installer.SKILLS:
        target = dest / name
        (target / 'scripts/run.py').write_text(installer.LEGACY_WRAPPER, encoding='utf-8')
        path = target / 'local-engine.json'
        metadata = json.loads(path.read_text(encoding='utf-8'))
        del metadata['installer']; del metadata['wrapper_schema']
        path.write_text(json.dumps(metadata), encoding='utf-8')
    assert installer.main(args(old, dest)) == 0


def test_only_selected_skill_changes(installed):
    old, new, dest = installed
    before = snapshot(dest)
    name = 'planning-cad-regulatory-suite'
    installer.main([*args(old, dest), '--only', name])
    after = snapshot(dest)
    assert {k: v for k, v in after.items() if not k.startswith(name + '/')} == {
        k: v for k, v in before.items() if not k.startswith(name + '/')}
    backup = next((dest.parent / 'planning-workbench-skill-backups').iterdir())
    assert sorted(p.name for p in backup.iterdir()) == ['migration.json', name]


def test_missing_selected_skill_fails_preflight(installed):
    old, new, dest = installed
    path = dest / installer.SKILLS[-1][1]
    path.rename(dest / 'kept-elsewhere')
    before = snapshot(dest.parent)
    with pytest.raises(ValueError, match='尚未安装'):
        installer.main(args(old, dest))
    assert snapshot(dest.parent) == before


def test_backup_failure_does_not_change_installed_skills(installed, monkeypatch):
    old, new, dest = installed
    before = snapshot(dest)
    original = installer.shutil.copytree
    def fail_one(source, destination, *a, **kw):
        if Path(source).name == 'planning-cad-road-plan':
            raise OSError('injected backup failure')
        return original(source, destination, *a, **kw)
    monkeypatch.setattr(installer.shutil, 'copytree', fail_one)
    with pytest.raises(OSError, match='backup failure'):
        installer.main(args(old, dest))
    assert snapshot(dest) == before
    backup = next((dest.parent / 'planning-workbench-skill-backups').iterdir())
    assert json.loads((backup / 'migration.json').read_text(encoding='utf-8'))['status'] == 'backup_failed_no_skill_updates'


def test_update_failure_rolls_back_all_managed_files(installed, monkeypatch):
    old, new, dest = installed
    before = snapshot(dest)
    original = installer._atomic_write
    injected = False
    def fail_once(path, value):
        nonlocal injected
        if path == dest / 'planning-cad-road-plan' / 'local-engine.json' and not injected:
            injected = True
            raise OSError('injected update failure')
        return original(path, value)
    monkeypatch.setattr(installer, '_atomic_write', fail_once)
    with pytest.raises(OSError, match='update failure'):
        installer.main(args(old, dest))
    assert snapshot(dest) == before
    backup = next((dest.parent / 'planning-workbench-skill-backups').iterdir())
    record = json.loads((backup / 'migration.json').read_text(encoding='utf-8'))
    assert record['status'] == 'rolled_back' and record['rollback_errors'] == []


def test_same_root_relocation_is_not_silently_inferred(installed):
    old, new, dest = installed
    before = snapshot(dest.parent)
    with pytest.raises(ValueError, match='当前路径相同'):
        installer.main(args(new, dest))
    assert snapshot(dest.parent) == before
