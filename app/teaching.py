"""Evidence-preserving comparison and assignment export. No model assertions."""
import io,json,zipfile
import math
from pathlib import Path

def _snapshot_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('missing or nonfinite numeric geometry')
    return float(value)


def _snapshot_point(entity, field, zfield, actual):
    point = entity.get(field)
    if not isinstance(point, (list, tuple)) or len(point) not in (2, 3):
        raise ValueError(f'missing {field}')
    xy = [_snapshot_number(v) for v in point[:2]]
    if len(point) == 3:
        z = _snapshot_number(point[2])
        if zfield in entity and not math.isclose(z, _snapshot_number(entity[zfield]), rel_tol=0, abs_tol=1e-9):
            raise ValueError(f'inconsistent {zfield}')
    elif zfield in entity:
        z = _snapshot_number(entity[zfield])
    elif actual:
        raise ValueError(f'unrecorded {zfield}; zero elevation cannot be assumed')
    else:
        z = 0.0  # The deterministic result schema is explicitly two-dimensional.
    return xy + [z]


def _snapshot_normal(entity, actual):
    value = entity.get('normal') if actual else entity.get('normal', [0, 0, 1])
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('unrecorded entity normal')
    return [_snapshot_number(v) for v in value]


def _snapshot_geometry(entity, actual):
    kind = entity.get('type')
    if not isinstance(entity.get('layer'), str):
        raise ValueError('unrecorded layer')
    result = {'type': kind, 'layer': entity['layer']}
    if kind == 'line':
        result['ends'] = sorted([_snapshot_point(entity, 'start', 'start_z', actual),
                                 _snapshot_point(entity, 'end', 'end_z', actual)])
    elif kind == 'arc':
        result.update(center=_snapshot_point(entity, 'center', 'center_z', actual),
                      normal=_snapshot_normal(entity, actual), radius=_snapshot_number(entity.get('radius')))
        start = _snapshot_number(entity.get('start_angle'))
        end = _snapshot_number(entity.get('end_angle'))
        if entity.get('clockwise', False):
            start, end = end, start
        if result['radius'] <= 0 or abs((end - start) % math.tau) < 1e-10:
            raise ValueError('degenerate arc')
        result['start_angle'], result['end_angle'] = start % math.tau, end % math.tau
        # Angular tolerance alone would hide large linear errors at large radii.
        for key, angle in (('start_point', start % math.tau), ('end_point', end % math.tau)):
            result[key] = [result['center'][0] + result['radius'] * math.cos(angle),
                           result['center'][1] + result['radius'] * math.sin(angle)]
    elif kind == 'polyline':
        points = entity.get('points')
        if (not isinstance(points, list) or len(points) < 2
                or any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in points)):
            raise ValueError('unrecorded polyline vertices')
        if not isinstance(entity.get('closed'), bool):
            raise ValueError('unrecorded polyline closed state')
        bulges = entity.get('bulges') if actual else entity.get('bulges', [0] * len(points))
        if not isinstance(bulges, (list, tuple)) or len(bulges) != len(points):
            raise ValueError('unrecorded polyline bulges')
        result.update(points=[[_snapshot_number(v) for v in p] for p in points],
                      closed=entity['closed'], normal=_snapshot_normal(entity, actual),
                      elevation=_snapshot_number(entity.get('elevation') if actual else entity.get('elevation', 0)),
                      bulges=[_snapshot_number(v) for v in bulges])
        if not entity['closed']:
            result['bulges'][-1] = 0.0  # Last bulge has no segment in an open polyline.
    elif kind == 'text':
        if not isinstance(entity.get('text'), str):
            raise ValueError('unrecorded text content')
        result.update(position=_snapshot_point(entity, 'position', 'position_z', actual),
                      text=entity['text'], height=_snapshot_number(entity.get('height')))
    else:
        raise ValueError(f'unsupported entity type: {kind}')
    return result


def _snapshot_equal(a, b, tolerance):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=0, abs_tol=tolerance)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_snapshot_equal(x, y, tolerance) for x, y in zip(a, b))
    return a == b


def compare_cad_snapshot(job_result, readback):
    """Compare saved audit geometry with calculated entities, never by job ID.

    This does not reopen current DWG bytes or compare fonts, colors or views.
    Older readbacks missing Z/normal/bulge remain unknown rather than assuming 2D.
    """
    expected = job_result.get('entities') if isinstance(job_result, dict) else None
    actual = readback.get('entities') if isinstance(readback, dict) else None
    result = {'status': 'unknown', 'coordinate_absolute_tolerance': 1e-6,
              'angle_absolute_tolerance_radians': 1e-7, 'relative_tolerance': 0,
              'expected_count': len(expected) if isinstance(expected, list) else None,
              'actual_count': len(actual) if isinstance(actual, list) else None,
              'matched_count': 0, 'changed_count': 0, 'missing_count': 0, 'extra_count': 0,
              'uncomparable_count': 0, 'difference_count': None, 'differences': [], 'notes': [],
              'scope': 'recorded geometry, text and layer; not font/color/view or current DWG bytes'}
    if not isinstance(expected, list) or not expected:
        result['notes'].append('calculated entities are missing or empty')
        return result
    if not isinstance(actual, list):
        result['notes'].append('saved CAD readback/entities are missing')
        return result
    complete = True
    if type(readback.get('entity_count')) is not int or readback['entity_count'] != len(actual) or readback.get('truncated'):
        complete = False
        result['notes'].append('readback count is missing, inconsistent or truncated')
    expected_units = (job_result.get('spec') or {}).get('units')
    actual_code = readback.get('units')
    actual_units = {6: 'm', 4: 'mm', 5: 'cm', 2: 'ft', 1: 'in'}.get(actual_code) if type(actual_code) is int else None
    if expected_units not in ('m', 'mm', 'cm', 'ft', 'in') or actual_units is None:
        complete = False
        result['notes'].append('drawing units or calculated units are unverified')
    unit_difference = actual_units is not None and expected_units in ('m', 'mm', 'cm', 'ft', 'in') and actual_units != expected_units
    result['units'] = {'calculated': expected_units, 'recorded_cad': actual_units, 'different': unit_difference}
    for name, values in (('calculated', expected), ('recorded', actual)):
        ids = [e.get('id') if isinstance(e, dict) else None for e in values]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            result['notes'].append(f'{name} entity IDs are absent or duplicated; correspondence is unknown')
            result['uncomparable_count'] = max(len(expected), len(actual))
            return result
    expected_by_id = {e['id']: e for e in expected}
    actual_by_id = {e['id']: e for e in actual}
    for entity_id in sorted(set(expected_by_id) | set(actual_by_id)):
        if entity_id not in actual_by_id:
            result['missing_count'] += 1
            result['differences'].append({'entity_id': entity_id, 'kind': 'missing_from_saved_cad'})
            continue
        if entity_id not in expected_by_id:
            result['extra_count'] += 1
            result['differences'].append({'entity_id': entity_id, 'kind': 'extra_in_saved_cad'})
            continue
        try:
            a = _snapshot_geometry(expected_by_id[entity_id], False)
            b = _snapshot_geometry(actual_by_id[entity_id], True)
        except (TypeError, ValueError, OverflowError) as exc:
            result['uncomparable_count'] += 1
            result['differences'].append({'entity_id': entity_id, 'kind': 'unknown_geometry', 'reason': str(exc)})
            continue
        fields = []
        for key in sorted(set(a) | set(b)):
            if key in ('start_angle', 'end_angle') and key in a and key in b:
                same = abs(math.remainder(a[key] - b[key], math.tau)) <= 1e-7
            else:
                same = _snapshot_equal(a.get(key), b.get(key), 1e-6)
            if not same:
                fields.append(key)
        if fields:
            result['changed_count'] += 1
            result['differences'].append({'entity_id': entity_id, 'kind': 'changed', 'fields': fields})
        else:
            result['matched_count'] += 1
    result['difference_count'] = result['changed_count'] + result['missing_count'] + result['extra_count']
    if not complete:
        result['status'] = 'unknown'
    elif result['difference_count'] or unit_difference:
        result['status'] = 'different'
    elif result['uncomparable_count']:
        result['status'] = 'unknown'
    else:
        result['status'] = 'matched'
    return result


def compare_jobs(a,b):
    if not a.get('result') or not b.get('result'):raise ValueError('两个任务都需要真实计算结果，失败任务可用于诊断比较')
    sa,sb=a['result']['spec'],b['result']['spec']
    if sa.get('units')!=sb.get('units') or sa.get('coordinate_reference')!=sb.get('coordinate_reference'):
        raise ValueError('方案单位或坐标基准不同，必须先完成真实转换')
    ra={r['id']:r for r in sa.get('roads',[])};rb={r['id']:r for r in sb.get('roads',[])}
    changes=[]
    for rid in sorted(set(ra)|set(rb)):
        if ra.get(rid)!=rb.get(rid):changes.append({'road_id':rid,'change':'added' if rid not in ra else 'removed' if rid not in rb else 'modified','before':ra.get(rid),'after':rb.get(rid)})
    parameters={k:{'before':sa.get(k),'after':sb.get(k)} for k in ('left_width','right_width','junction_radius','constraints','components','boundary') if sa.get(k)!=sb.get(k)}
    ma,mb=a['result'].get('metrics',{}),b['result'].get('metrics',{})
    metrics={k:{'A':ma.get(k),'B':mb.get(k),'delta':mb[k]-ma[k]} for k in ma.keys()&mb.keys() if isinstance(ma[k],(int,float)) and isinstance(mb[k],(int,float))}
    return {'A':a['id'],'B':b['id'],'units':sa.get('units'),'road_changes':changes,'parameter_changes':parameters,'metrics':metrics,'errors':{'A':a['result']['report']['errors'],'B':b['result']['report']['errors']},'duration_seconds':{'A':a.get('duration_seconds'),'B':b.get('duration_seconds')},'usage':{'A':a.get('usage'),'B':b.get('usage')},'cost':None,'traffic_effect':None,'note':'几何与参数差异；耗时不是公平模型基准，费用和交通效应未推算。'}

def assignment_bytes(store,job_id):
    job=store.get('jobs',job_id)
    if job['status'] not in ('succeeded','failed','canceled','interrupted'):raise ValueError('任务尚未结束')
    project=store.get('projects',job['project_id'])
    audit=[x for x in store.list('cad_audit') if x.get('job_id')==job_id]
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        def put(name,obj):z.writestr(name,json.dumps(obj,ensure_ascii=False,indent=2))
        put('parameters.json',(job.get('result') or {}).get('spec',job['spec']))
        put('quality.json',(job.get('result') or {}).get('report',{'status':job['status']}))
        put('process.json',{'id':job['id'],'status':job['status'],'events':job['events'],'duration_seconds':job.get('duration_seconds'),'usage':job.get('usage'),'mock':job['mock'],'runtime':job['runtime'],'provider':job['provider']})
        put('revision-history.json',project.get('history',[]))
        put('cad-operations.json',audit)
        artifacts=store.folder/'artifacts'/job_id
        drawing=artifacts/'drawing.dxf'
        if job['status']=='succeeded' and drawing.exists():z.write(drawing,'drawing.dxf')
        count=0
        snapshots=[]
        for action in audit:
            value=action.get('result',{})
            path=value.get('path') or value.get('saved_path') or value.get('file')
            if action['action']=='save' and path:
                p=Path(path).resolve();allowed=(store.folder/'cad').resolve()
                if p.is_relative_to(allowed) and p.is_file() and p.suffix.lower()=='.dwg':
                    count+=1
                    archive_name=f'cad-saved-{count}.dwg'
                    z.write(p,archive_name)
                    snapshots.append({'archive_file':archive_name,'audit_id':action.get('id'),
                        'job_id':job_id,'document_id':action.get('document_id'),
                        'audit_status':action.get('status'),'saved_at':action.get('updated_at') or action.get('created_at'),
                        'actual_readback':value.get('readback'),
                        'comparison':compare_cad_snapshot(job.get('result'),value.get('readback')),
                        'dwg_bytes_reopened_and_verified':False})
        put('cad-snapshots.json',{'job_id':job_id,'snapshots':snapshots,
            'note':'保存审计回读的对照，打包时未重新打开 DWG 核验；job_id 不证明几何一致。'})
        z.writestr('READ-ME.txt',f"规绘作业包\n数据为 {'synthetic 教学样例' if job.get('synthetic') else '用户导入，来源由用户核实'}。\n任务状态：{job['status']}\nparameters.json 和 drawing.dxf 对应计算任务；DWG 是 CAD 保存时的快照，可能因人工编辑、修改后撤销等操作与该任务不同。\ncad-snapshots.json 对每份 DWG 记录实际保存回读及 matched（记录几何一致）/different（存在差异）/unknown（证据不足）状态，并列出匹配、变化、缺失、额外和无法核验的实体数量；同一 job_id 不代表已匹配。\n对照包含坐标、Z、法向、bulge、文字内容和图层；采用固定绝对浮点容差与圆弧角度同义判断，不检查字体、颜色或视图。以上是保存审计回读的对照，打包时未重新打开 DWG 核验。\n无CAD保存记录时不包含DWG；DXF为可编辑成果。\n检查结果不代替教师审图。模型未知用量和成本保留空值。\n")
    return buffer.getvalue()
