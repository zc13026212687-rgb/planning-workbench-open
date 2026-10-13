import copy
import io
import json
import math
import zipfile

import pytest

from app.store import Store
from app.teaching import assignment_bytes, compare_cad_snapshot


@pytest.fixture
def pair():
    entities = [
        {'id': 'line', 'type': 'line', 'layer': 'ROAD_EDGE', 'start': [0, 0], 'end': [10, 0]},
        {'id': 'arc', 'type': 'arc', 'layer': 'ROAD_JUNCTION', 'center': [10, 5], 'radius': 5,
         'start_angle': -math.pi/2, 'end_angle': 0},
        {'id': 'poly', 'type': 'polyline', 'layer': 'BOUNDARY', 'points': [[0, 0], [10, 0], [10, 10]], 'closed': True},
        {'id': 'text', 'type': 'text', 'layer': 'ROAD_LABEL', 'position': [3, 4], 'text': '教学道路', 'height': 2},
    ]
    actual = copy.deepcopy(entities)
    actual[0].update(start_z=0, end_z=0)
    actual[1].update(center_z=0, normal=[0, 0, 1], start_angle=3*math.pi/2)
    actual[2].update(elevation=0, normal=[0, 0, 1], bulges=[0, 0, 0])
    actual[3].update(position_z=0, style_name='PW_Chinese_test')
    return {'entities': entities, 'spec': {'units': 'm'}, 'report': {}}, {
        'entities': actual, 'entity_count': 4, 'units': 6, 'document_id': 'test-doc'}


def test_complete_geometry_matches_independent_of_native_handles_and_style(pair):
    expected, actual = pair
    for i, entity in enumerate(actual['entities']):
        entity.update(handle=f'{i+10:X}', color_index=256)
    actual['entities'].reverse()
    result = compare_cad_snapshot(expected, actual)
    assert result['status'] == 'matched' and result['matched_count'] == 4
    assert result['difference_count'] == 0 and result['uncomparable_count'] == 0


def test_arc_angle_synonyms_and_small_numeric_noise_match(pair):
    expected, actual = pair
    actual['entities'][0]['end'][0] += 1e-8
    actual['entities'][1]['start_angle'] += math.tau
    actual['entities'][1]['end_angle'] -= math.tau
    assert compare_cad_snapshot(expected, actual)['status'] == 'matched'
    actual['entities'][0]['start'], actual['entities'][0]['end'] = actual['entities'][0]['end'], actual['entities'][0]['start']
    assert compare_cad_snapshot(expected, actual)['status'] == 'matched'


@pytest.mark.parametrize('change', ['coordinate', 'line_z', 'arc_z', 'arc_normal', 'poly_z', 'poly_bulge', 'text_z', 'text_content', 'layer'])
def test_geometry_or_semantic_changes_never_match(pair, change):
    expected, actual = pair
    line, arc, poly, text = actual['entities']
    if change == 'coordinate': line['end'][0] += 0.001
    elif change == 'line_z': line['end_z'] = 1
    elif change == 'arc_z': arc['center_z'] = 1
    elif change == 'arc_normal': arc['normal'] = [0, 1, 0]
    elif change == 'poly_z': poly['elevation'] = 1
    elif change == 'poly_bulge': poly['bulges'][0] = 0.5
    elif change == 'text_z': text['position_z'] = 1
    elif change == 'text_content': text['text'] = '手工修改'
    else: line['layer'] = 'OTHER_LAYER'
    result = compare_cad_snapshot(expected, actual)
    assert result['status'] == 'different'
    assert result['matched_count'] == 3 and result['changed_count'] == result['difference_count'] == 1


def test_omitted_and_extra_entities_are_counted_even_with_same_document_and_job_id(pair):
    expected, actual = pair
    actual['entities'].pop()
    actual['entity_count'] = 3
    missing = compare_cad_snapshot(expected, actual)
    assert missing['status'] == 'different' and missing['missing_count'] == 1
    actual['entities'].append({'id': 'external-object', 'type': 'unsupported', 'handle': 'ZZ'})
    actual['entity_count'] = 4
    result = compare_cad_snapshot(expected, actual)
    assert result['status'] == 'different' and result['matched_count'] == 3
    assert result['missing_count'] == result['extra_count'] == 1 and result['difference_count'] == 2


@pytest.mark.parametrize('change', ['none', 'no_entities', 'no_count', 'bad_count', 'truncated', 'no_z', 'no_normal', 'no_bulge', 'no_units', 'duplicate_id'])
def test_missing_or_incomplete_readback_cannot_be_reported_matched(pair, change):
    expected, actual = pair
    if change == 'none': actual = None
    elif change == 'no_entities': actual.pop('entities')
    elif change == 'no_count': actual.pop('entity_count')
    elif change == 'bad_count': actual['entity_count'] = 5
    elif change == 'truncated': actual['truncated'] = True
    elif change == 'no_z': actual['entities'][0].pop('start_z')
    elif change == 'no_normal': actual['entities'][1].pop('normal')
    elif change == 'no_bulge': actual['entities'][2].pop('bulges')
    elif change == 'no_units': actual.pop('units')
    else: actual['entities'][1]['id'] = 'line'
    assert compare_cad_snapshot(expected, actual)['status'] == 'unknown'


def test_units_mismatch_is_different_without_scaling(pair):
    expected, actual = pair
    actual['units'] = 4
    result = compare_cad_snapshot(expected, actual)
    assert result['status'] == 'different' and result['units']['different']


def test_fixed_tolerance_does_not_hide_changes_at_large_coordinates_or_arc_radii(pair):
    expected, actual = pair
    expected['entities'][0]['end'][0] = 1e8
    actual['entities'][0]['end'][0] = 1e8 + 0.01
    assert compare_cad_snapshot(expected, actual)['status'] == 'different'
    actual['entities'][0]['end'][0] = 1e8
    expected['entities'][1]['radius'] = actual['entities'][1]['radius'] = 1e7
    actual['entities'][1]['end_angle'] = 5e-8  # 0.5 drawing units, despite a small angular delta.
    assert compare_cad_snapshot(expected, actual)['status'] == 'different'


def test_zip_records_each_saved_snapshot_and_explains_reverted_geometry(tmp_path, pair):
    expected, actual = pair
    store = Store(tmp_path)
    project = store.put('projects', {'spec': expected['spec'], 'history': []})
    store.put('jobs', {'id': 'modified-job', 'project_id': project['id'], 'status': 'succeeded',
                      'spec': expected['spec'], 'result': expected, 'events': [], 'mock': False,
                      'runtime': 'builtin', 'provider': None, 'synthetic': True})
    cad = tmp_path / 'cad'
    cad.mkdir()
    reverted = copy.deepcopy(actual)
    reverted['entities'][0]['end'][0] = 8
    for index, readback in enumerate((actual, reverted, None), 1):
        output = cad / f'snapshot-{index}.dwg'
        output.write_bytes(b'test-only DWG placeholder; no real CAD is invoked')
        store.put('cad_audit', {'id': f'save-{index}', 'job_id': 'modified-job', 'action': 'save',
                               'document_id': 'test-doc', 'status': 'succeeded',
                               'result': {'path': str(output), 'readback': readback}})
    with zipfile.ZipFile(io.BytesIO(assignment_bytes(store, 'modified-job'))) as archive:
        manifest = json.loads(archive.read('cad-snapshots.json'))
        entries = {entry['audit_id']: entry for entry in manifest['snapshots']}
        assert entries['save-1']['comparison']['status'] == 'matched'
        assert entries['save-2']['comparison']['status'] == 'different'
        assert entries['save-2']['comparison']['changed_count'] == 1
        assert entries['save-3']['comparison']['status'] == 'unknown'
        assert entries['save-2']['actual_readback'] == reverted
        assert all(entry['archive_file'] in archive.namelist() for entry in entries.values())
        assert all(entry['dwg_bytes_reopened_and_verified'] is False for entry in entries.values())
        readme = archive.read('READ-ME.txt').decode('utf-8')
        assert '修改后撤销' in readme and '打包时未重新打开 DWG 核验' in readme
        assert 'parameters.json 和 drawing.dxf 对应计算任务' in readme
