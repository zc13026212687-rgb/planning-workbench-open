import copy
import csv
import json

import ezdxf
import pytest
from shapely.geometry import Polygon, box

from app.cad import validate_entities
from app.parcels import (bind_attributes, build_control_sheet, export_parcels_csv, export_parcels_dxf,
                         export_parcels_json, generate, get_example)


def codes(result):
    return {item['code'] for item in result['report']['errors']}


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def explicit():
    return {'kind': 'regulatory_parcels', 'units': 'm', 'coordinate_reference': 'local_cartesian',
            'mode': 'explicit', 'boundary': rect(0, 0, 100, 100),
            'parcels': [{'id': 'A', 'polygon': rect(0, 0, 50, 100)},
                        {'id': 'B', 'polygon': rect(50, 0, 100, 100)}]}


def test_analytic_crossroad_union_and_conservation():
    spec = get_example()
    before = copy.deepcopy(spec)
    result = generate(spec)
    assert not codes(result)
    assert spec == before
    m = result['metrics']
    assert m['boundary_gross_area_m2'] == 43200
    assert m['boundary_holes_area_m2'] == 900
    assert m['boundary_area_m2'] == 42300
    assert m['road_area_m2'] == 20 * 180 + 16 * 240 - 20 * 16
    assert m['parcel_area_m2'] == 35180
    assert m['unallocated_area_m2'] == 0
    assert m['area_conservation_residual_m2'] == pytest.approx(0)
    assert m['parcel_count'] == 4
    assert sorted(p['data']['area_m2'] for p in result['parcels']) == [8120, 9020, 9020, 9020]
    assert len(validate_entities(result['entities'])) == len(result['entities'])


def test_indicators_are_conditional_arithmetic_and_missing_stays_none():
    result = generate(get_example())
    row = result['parcels'][0]['data']
    assert row['max_gfa_m2'] == pytest.approx(row['area_m2'] * 1.8)
    assert row['max_building_footprint_m2'] == pytest.approx(row['area_m2'] * .3)
    assert row['min_green_area_m2'] == pytest.approx(row['area_m2'] * .35)
    assert row['area_ha'] == pytest.approx(row['area_m2'] / 10000)
    assert row['share_of_boundary_pct'] == pytest.approx(row['area_m2'] / 42300 * 100)
    last = result['parcels'][3]['data']
    assert last['far_max'] is None and last['max_gfa_m2'] is None
    assert result['metrics']['indicator_compliance'] == 'not_evaluated'
    empty = generate(explicit())
    assert all(p['data']['indicator_status'] == 'not_supplied' for p in empty['parcels'])
    assert any(w['code'] == 'missing_indicators' for w in empty['report']['warnings'])


@pytest.mark.parametrize('field,value,code', [
    ('units', 'mm', 'units_required'), ('units', None, 'units_required'),
    ('coordinate_reference', 'EPSG:4326', 'unsupported_crs'),
    ('mode', None, 'mode_required'), ('kind', 'anything', 'invalid_kind'),
    ('sliver_threshold_m2', float('nan'), 'invalid_sliver_threshold')])
def test_invalid_contract_produces_no_entities(field, value, code):
    spec = explicit()
    spec[field] = value
    result = generate(spec)
    assert code in codes(result)
    assert not result['entities']


@pytest.mark.parametrize('polygon', [
    [[0, 0], [10, 10], [0, 10], [10, 0]],
    [[0, 0], [5, 0], [10, 0]],
    [[0, 0], [10, 0], [10, 0], [10, 10], [0, 10]],
    [[0, 0], [float('nan'), 0], [10, 10]],
    {'outer': rect(0, 0, 10, 10), 'holes': [rect(20, 20, 30, 30)]},
    {'outer': rect(0, 0, 10, 10), 'holes': [rect(2, 2, 7, 7), rect(4, 4, 8, 8)]}])
def test_invalid_polygons_rejected_without_silent_repair(polygon):
    spec = explicit()
    spec['boundary'] = polygon
    result = generate(spec)
    assert 'invalid_boundary' in codes(result)
    assert not result['entities']


def test_overlap_outside_and_duplicate_id_rejected():
    spec = explicit()
    spec['parcels'][1]['polygon'] = rect(49, 0, 100, 100)
    assert 'parcel_overlap' in codes(generate(spec))
    spec['parcels'][1]['polygon'] = rect(50, 0, 101, 100)
    assert 'parcel_outside_boundary' in codes(generate(spec))
    spec['parcels'][1]['id'] = 'A'
    assert 'duplicate_or_invalid_id' in codes(generate(spec))


@pytest.mark.parametrize('key,value', [('far_max', float('nan')), ('far_max', True),
    ('green_min_pct', 101), ('coverage_max_pct', -1), ('height_max_m', float('inf')),
    ('land_use_code', ''), ('land_use_name', 'bad\nlabel'), ('not_an_indicator', 5)])
def test_invalid_indicators_fail_instead_of_ignored(key, value):
    spec = explicit()
    spec['parcels'][0]['attributes'] = {key: value}
    result = generate(spec)
    assert codes(result) & {'invalid_attribute', 'unknown_attribute'}
    assert not result['entities']


def test_explicit_hole_excluded_and_unallocated_accounted():
    spec = explicit()
    spec['parcels'] = [{'id': 'COURT', 'polygon': {'outer': rect(0, 0, 100, 100), 'holes': [rect(40, 40, 60, 60)]}}]
    result = generate(spec)
    assert not codes(result)
    assert result['metrics']['parcel_area_m2'] == 9600
    assert result['metrics']['unallocated_area_m2'] == 400
    assert len(result['parcels'][0]['polygon']['holes']) == 1
    assert len([e for e in result['entities'] if e['layer'] == 'PARCEL_HOLE']) == 1
    poly = Polygon(spec['parcels'][0]['polygon']['outer'], spec['parcels'][0]['polygon']['holes'])
    for entity in result['entities']:
        if entity['type'] == 'text':
            assert poly.covers(box(*entity['label_envelope']))


def test_explicit_parcel_cannot_fill_boundary_hole():
    spec = explicit()
    spec['boundary'] = {'outer': rect(0, 0, 100, 100), 'holes': [rect(20, 20, 30, 30)]}
    assert 'parcel_outside_boundary' in codes(generate(spec))


def test_road_overlap_uses_union_even_duplicate_geometry_distinct_id():
    spec = get_example()
    spec['roads'].append({**copy.deepcopy(spec['roads'][0]), 'id': 'SAME_GEOMETRY_NEW_ID'})
    result = generate(spec)
    assert not codes(result)
    assert result['metrics']['road_area_m2'] == 7120
    assert result['metrics']['parcel_area_m2'] == 35180
    check = next(c for c in result['report']['checks'] if c['code'] == 'road_union')
    assert check['sum_individual_road_area_m2'] > check['union_road_area_m2']


@pytest.mark.parametrize('mutator,expected', [
    (lambda s: s['roads'][0].update(total_width_m=float('nan')), 'invalid_road_width'),
    (lambda s: s['roads'][0].update(total_width_m=0), 'invalid_road_width'),
    (lambda s: s['roads'][0].update(centerline=[[0, 0], [float('inf'), 1]]), 'invalid_centerline'),
    (lambda s: s['roads'][0].update(centerline=[[0, 0], [0, 0]]), 'invalid_centerline'),
    (lambda s: s['roads'][0].update(centerline=[[400, 400], [500, 500]]), 'road_outside_boundary'),
    (lambda s: s['roads'][1].update(id=s['roads'][0]['id']), 'duplicate_or_invalid_id')])
def test_invalid_roads(mutator, expected):
    spec = get_example()
    mutator(spec)
    result = generate(spec)
    assert expected in codes(result)
    assert not result['entities']


def test_explicit_road_conflict_and_unknown_generated_attributes():
    spec = explicit()
    spec['roads'] = [{'id': 'R1', 'centerline': [[50, 0], [50, 100]], 'total_width_m': 10}]
    assert 'parcel_road_overlap' in codes(generate(spec))
    spec = get_example()
    spec['parcel_attributes']['P999'] = {'far_max': 2}
    assert 'unknown_parcel_id' in codes(generate(spec))


def test_small_parcels_preserved_and_ids_stable_on_road_order():
    spec = {'kind': 'regulatory_parcels', 'units': 'm', 'coordinate_reference': 'local_cartesian',
            'mode': 'roads', 'boundary': rect(0, 0, 10, 10), 'sliver_threshold_m2': 5,
            'roads': [{'id': 'R', 'centerline': [[1, 0], [1, 10]], 'total_width_m': 1.8}]}
    result = generate(spec)
    assert not codes(result)
    assert result['metrics']['parcel_count'] == 2
    assert result['metrics']['small_parcel_count'] == 1
    assert sorted(p['data']['area_m2'] for p in result['parcels']) == pytest.approx([1, 81])
    spec = get_example()
    first = generate(spec)
    spec['roads'].reverse()
    second = generate(spec)
    assert [(p['id'], p['data']['area_m2']) for p in first['parcels']] == [(p['id'], p['data']['area_m2']) for p in second['parcels']]


def test_dxf_roundtrip_holes_csv_json_and_no_overwrite(tmp_path):
    result = generate(get_example())
    dxf_path, csv_path, json_path = [tmp_path / name for name in ('parcels.dxf', 'parcels.csv', 'parcels.json')]
    export_parcels_dxf(result, dxf_path)
    export_parcels_csv(result, csv_path)
    export_parcels_json(result, json_path)
    doc = ezdxf.readfile(dxf_path)
    assert doc.units == 6
    audit = doc.audit()
    assert not audit.errors and not audit.fixes
    assert len(doc.modelspace()) == len(result['entities'])
    assert len(list(doc.modelspace().query('LWPOLYLINE[layer=="PARCEL_HOLE"]'))) == 1
    assert csv_path.read_bytes().startswith(b'\xef\xbb\xbf')
    parsed = json.loads(json_path.read_text(encoding='utf-8'))
    assert parsed['coordinate_reference'] == 'local_cartesian' and parsed['is_geojson'] is False
    assert parsed['parcels'][3]['data']['max_gfa_m2'] is None
    for exporter, path in ((export_parcels_dxf, dxf_path), (export_parcels_csv, csv_path), (export_parcels_json, json_path)):
        with pytest.raises(FileExistsError):
            exporter(result, path)


def test_control_sheet_editable_a3_original_polygon_retained(tmp_path):
    result = generate(get_example())
    sheet = build_control_sheet(result, 'P003')
    assert not sheet['report']['errors']
    assert sheet['bounds'] == [0, 0, .42, .297]
    assert sheet['data'] == result['parcels'][2]
    assert sheet['metrics']['map_scale_denominator'] > 1
    validate_entities(sheet['entities'])
    assert any(e.get('ring_role') == 'hole' for e in sheet['entities'])
    assert all(0 <= xy[0] <= .42 and 0 <= xy[1] <= .297 for e in sheet['entities']
               for xy in e.get('points', [e.get('position', [.1, .1])]))
    export_parcels_dxf(sheet, tmp_path / 'sheet.dxf')
    doc = ezdxf.readfile(tmp_path / 'sheet.dxf')
    assert not doc.audit().errors
    assert len(doc.modelspace()) == len(sheet['entities'])
    with pytest.raises(ValueError):
        build_control_sheet(result, 'NOPE')


def test_error_results_cannot_be_exported(tmp_path):
    spec = explicit()
    spec['units'] = 'unknown'
    result = generate(spec)
    for exporter in (export_parcels_dxf, export_parcels_csv, export_parcels_json):
        with pytest.raises(ValueError):
            exporter(result, tmp_path / exporter.__name__)


def test_csv_formula_like_names_are_literal_not_executable(tmp_path):
    spec = explicit()
    spec['parcels'][0]['attributes'] = {'land_use_name': '=1+1'}
    result = generate(spec)
    target = tmp_path / 'literal.csv'
    export_parcels_csv(result, target)
    with target.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]['land_use_name'] == "'=1+1"
    assert result['parcels'][0]['data']['land_use_name'] == '=1+1'


def test_geometry_signatures_are_deterministic_and_bound_after_confirmation():
    spec = get_example()
    before = copy.deepcopy(spec)
    first = generate(spec)
    assert first['geometry_bindings'] == generate(spec)['geometry_bindings']
    assert all(len(p['geometry_sha256']) == 64 for p in first['parcels'])
    assert all(first['geometry_bindings'][p['id']] == p['geometry_sha256'] for p in first['parcels'])
    assert any(w['code'] == 'caller_assigned' for w in first['report']['warnings'])
    bound_spec = bind_attributes(spec, first)
    assert spec == before and 'attribute_geometry_bindings' not in spec
    assert bound_spec['attribute_geometry_bindings'] == first['geometry_bindings']
    bound_result = generate(bound_spec)
    assert not codes(bound_result)
    assert all(p['data']['attribute_binding_status'] == 'geometry_bound' for p in bound_result['parcels'])
    assert not any(w['code'] == 'caller_assigned' for w in bound_result['report']['warnings'])
    bound_spec['roads'].reverse()
    assert not codes(generate(bound_spec))


def test_geometry_signature_normalizes_ring_start_direction_and_hole_order():
    spec = explicit()
    spec['parcels'] = [{'id': 'A', 'polygon': {'outer': rect(0, 0, 100, 100),
        'holes': [rect(10, 10, 20, 20), rect(70, 70, 80, 80)]}, 'attributes': {'far_max': 2}}]
    first = generate(spec)
    bound = bind_attributes(spec, first)
    polygon = bound['parcels'][0]['polygon']
    polygon['outer'] = list(reversed(polygon['outer'][2:] + polygon['outer'][:2]))
    polygon['holes'] = [list(reversed(ring[1:] + ring[:1])) for ring in reversed(polygon['holes'])]
    normalized = generate(bound)
    assert not codes(normalized)
    assert normalized['geometry_bindings'] == first['geometry_bindings']


def test_changed_road_width_rejects_stale_attributes_and_every_export(tmp_path):
    spec = get_example()
    bound = bind_attributes(spec, generate(spec))
    bound['roads'][0]['total_width_m'] = 24
    invalid = generate(bound)
    assert 'attribute_binding_mismatch' in codes(invalid)
    assert not invalid['entities'] and not invalid['parcels']
    assert invalid['geometry_bindings'] != bound['attribute_geometry_bindings']
    for exporter in (export_parcels_dxf, export_parcels_csv, export_parcels_json):
        with pytest.raises(ValueError):
            exporter(invalid, tmp_path / exporter.__name__)
    with pytest.raises(ValueError):
        build_control_sheet(invalid, 'P001')


def test_equal_area_different_geometry_cannot_reuse_bound_attributes():
    spec = explicit()
    for parcel in spec['parcels']:
        parcel['attributes'] = {'far_max': 2}
    bound = bind_attributes(spec, generate(spec))
    bound['parcels'][0]['polygon'] = rect(0, 0, 100, 50)
    bound['parcels'][1]['polygon'] = rect(0, 50, 100, 100)
    rejected = generate(bound)
    assert 'attribute_binding_mismatch' in codes(rejected)
    assert all(error.get('reason') == 'geometry_changed' for error in rejected['report']['errors'])


@pytest.mark.parametrize('mutation', ['remove_binding', 'new_id', 'empty_bindings'])
def test_nonempty_attributes_require_existing_id_binding(mutation):
    spec = explicit()
    spec['parcels'][0]['attributes'] = {'far_max': 2}
    bound = bind_attributes(spec, generate(spec))
    if mutation == 'remove_binding':
        del bound['attribute_geometry_bindings']['A']
    elif mutation == 'new_id':
        bound['parcels'][0]['id'] = 'NEW'
    else:
        bound['attribute_geometry_bindings'] = {}
    result = generate(bound)
    assert 'attribute_binding_mismatch' in codes(result)
    assert result['report']['errors'][0]['reason'] == 'missing_binding'


@pytest.mark.parametrize('value', [None, [], 'wrong', {'P001': 'bad'}, {'P001': 'G' * 64}])
def test_malformed_binding_schema_rejected(value):
    spec = get_example()
    spec['attribute_geometry_bindings'] = value
    result = generate(spec)
    assert 'attribute_binding_mismatch' in codes(result)
    assert result['report']['errors'][0]['reason'] == 'invalid_binding_schema'


def test_empty_indicators_need_no_binding_but_new_values_do():
    spec = explicit()
    spec['attribute_geometry_bindings'] = {}
    assert not codes(generate(spec))
    spec['parcels'][0]['attributes'] = {'far_max': 0}
    assert 'attribute_binding_mismatch' in codes(generate(spec))


def test_indicators_may_change_without_rebinding_unchanged_geometry():
    spec = get_example()
    bound = bind_attributes(spec, generate(spec))
    bound['parcel_attributes']['P001']['far_max'] = 2.3
    result = generate(bound)
    assert not codes(result)
    assert result['parcels'][0]['data']['max_gfa_m2'] == pytest.approx(9020 * 2.3)
    assert result['parcels'][0]['data']['attribute_binding_status'] == 'geometry_bound'


def test_confirmation_rejects_old_preview_and_different_indicators():
    spec = get_example()
    preview = generate(spec)
    changed = copy.deepcopy(spec)
    changed['roads'][0]['total_width_m'] = 24
    with pytest.raises(ValueError, match='几何不一致'):
        bind_attributes(changed, preview)
    changed = copy.deepcopy(spec)
    changed['parcel_attributes']['P001']['far_max'] = 4
    with pytest.raises(ValueError, match='指标不一致'):
        bind_attributes(changed, preview)
    with pytest.raises(ValueError):
        bind_attributes(spec, build_control_sheet(preview, 'P001'))
    preview['parcels'][0]['polygon']['outer'][0][0] += 1e-8
    with pytest.raises(ValueError):
        bind_attributes(spec, preview)


def test_binding_signatures_survive_sheet_and_json(tmp_path):
    spec = get_example()
    result = generate(bind_attributes(spec, generate(spec)))
    sheet = build_control_sheet(result, 'P003')
    digest = result['geometry_bindings']['P003']
    assert sheet['data']['geometry_sha256'] == digest
    assert sheet['geometry_bindings'] == {'P003': digest}
    assert sheet['parcels'][0]['geometry_sha256'] == digest
    target = tmp_path / 'sheet.json'
    export_parcels_json(sheet, target)
    payload = json.loads(target.read_text(encoding='utf-8'))
    assert payload['geometry_bindings'] == {'P003': digest}
    assert payload['source_spec']['attribute_geometry_bindings']['P003'] == digest
    assert payload['geometry_binding_algorithm'] == 'sha256_normalized_wkb_2d_le_v1'
