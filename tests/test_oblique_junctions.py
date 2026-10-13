import copy
import math

import ezdxf
import pytest
from app.geometry import generate, export_dxf, import_dxf


def source(angle=60, kind='X', radius=4):
    u=[math.cos(math.radians(angle)),math.sin(math.radians(angle))]
    return {'units':'m','coordinate_reference':'local_cartesian','left_width':8,'right_width':8,
            'junction_radius':radius,'qa_tolerance':0.001,'roads':[
                {'id':'main','junction_type':'at_grade','segments':[{'type':'line','start':[-120,0],'end':[120,0]}]},
                {'id':'branch','junction_type':'at_grade','segments':[{'type':'line','start':[0,0] if kind=='T' else [-100*x for x in u],'end':[100*x for x in u]}]}],
            'constraints':[],'context_entities':[]}


def errors(result):return [x['code'] for x in result['report']['errors']]


def tangent_checks(result):
    edges=[e for e in result['entities'] if e['layer']=='ROAD_EDGE']
    arcs=[e for e in result['entities'] if e['layer']=='ROAD_JUNCTION']
    for arc in arcs:
        sweep=(arc['end_angle']-arc['start_angle'])%math.tau
        assert 0<sweep<math.pi
        for angle in (arc['start_angle'],arc['end_angle']):
            p=[arc['center'][i]+arc['radius']*f(angle) for i,f in enumerate((math.cos,math.sin))]
            incident=[e for e in edges if min(math.dist(p,e['start']),math.dist(p,e['end']))<2e-6]
            assert len(incident)==1
            vector=[incident[0]['end'][i]-incident[0]['start'][i] for i in (0,1)]
            radial=[p[i]-arc['center'][i] for i in (0,1)]
            assert abs(sum(vector[i]*radial[i] for i in (0,1)))/math.hypot(*vector)<2e-6


@pytest.mark.parametrize('angle',[30,35,45,60,75,90,105,120,135,145,150])
@pytest.mark.parametrize('kind',['T','X'])
def test_oblique_t_x_true_tangency_widths_closed_geometry(angle,kind):
    spec=source(angle,kind); before=copy.deepcopy(spec); result=generate(spec)
    assert not errors(result),result['report']
    assert spec==before
    assert result['metrics']['junction_count']==1
    assert len([e for e in result['entities'] if e['layer']=='ROAD_JUNCTION'])==(2 if kind=='T' else 4)
    tangent_checks(result)
    roads={r['id']:r['segments'][0] for r in spec['roads']}
    for edge in (e for e in result['entities'] if e['layer']=='ROAD_EDGE'):
        s=roads[edge['road_id']];d=[s['end'][i]-s['start'][i] for i in (0,1)]
        for p in (edge['start'],edge['end']):
            assert abs((p[0]-s['start'][0])*d[1]-(p[1]-s['start'][1])*d[0])/math.hypot(*d)==pytest.approx(8,abs=1e-7)
    if kind=='X':
        sin=math.sin(math.radians(angle))
        expected=(240+200)*16-4*8**2/sin+4*4**2/sin-math.pi*4**2
        assert result['metrics']['road_area']==pytest.approx(expected,abs=.04)


@pytest.mark.parametrize('angle',[30,60,120,150])
def test_oblique_rotation_translation_and_direction_reversal(angle):
    spec=source(angle); baseline=generate(spec)
    rot=.317;c,s=math.cos(rot),math.sin(rot)
    for road in spec['roads']:
        segment=road['segments'][0]
        for key in ('start','end'):
            x,y=segment[key];segment[key]=[c*x-s*y+10000,s*x+c*y-25000]
        segment['start'],segment['end']=segment['end'],segment['start']
    result=generate(spec);assert not errors(result),result['report'];tangent_checks(result)
    assert result['metrics']['road_area']==pytest.approx(baseline['metrics']['road_area'],abs=.001)


@pytest.mark.parametrize('kind',['T','X'])
def test_oblique_zero_radius_sharp_boundary(kind):
    result=generate(source(60,kind,0));assert not errors(result)
    assert not any(e['layer']=='ROAD_JUNCTION' for e in result['entities'])


def test_asymmetric_oblique_direction_reversal_and_roundtrip(tmp_path):
    spec=source(60);spec['roads'][0].update(left_width=9,right_width=7)
    spec['roads'][1].update(left_width=6,right_width=5)
    result=generate(spec);assert not errors(result),result['report'];tangent_checks(result)
    p=tmp_path/'oblique.dxf';export_dxf(result,p)
    drawing=ezdxf.readfile(p);assert len(drawing.modelspace().query('ARC'))==4
    restored=generate(import_dxf(p));assert not errors(restored);tangent_checks(restored)
    assert restored['metrics']['road_area']==pytest.approx(result['metrics']['road_area'],abs=.001)
    for r in spec['roads']:
        seg=r['segments'][0];seg['start'],seg['end']=seg['end'],seg['start']
        r['left_width'],r['right_width']=r['right_width'],r['left_width']
    reversed_result=generate(spec);assert not errors(reversed_result);tangent_checks(reversed_result)
    assert reversed_result['metrics']['road_area']==pytest.approx(result['metrics']['road_area'],abs=.001)


@pytest.mark.parametrize('angle',[1,15,29.9,150.1,170])
def test_unsupported_acute_intersection_reports_algorithm_gate(angle):
    result=generate(source(angle));assert 'junction_angle_out_of_range' in errors(result)
    assert not result['entities']


def test_offset_reversal_short_arm_unknown_and_y_node_rejected():
    spec=source(30);spec['roads'][1].update(left_width=2,right_width=2)
    assert 'unsupported_offset_reversal' in errors(generate(spec))
    spec=source(30,'T');spec['roads'][1]['segments'][0]['end']=[5,5/math.sqrt(3)]
    assert 'insufficient_junction_space' in errors(generate(spec))
    spec=source();spec['roads'][1]['junction_type']='unknown'
    assert 'needs_confirmation' in errors(generate(spec))
    spec=source();spec['roads']=[]
    for i in range(3):
        a=math.tau*i/3;spec['roads'].append({'id':str(i),'segments':[{'type':'line','start':[0,0],'end':[100*math.cos(a),100*math.sin(a)]}]})
    assert 'unsupported_node' in errors(generate(spec))


def test_teaching_variants_and_standalone_cli(tmp_path):
    import json
    from app.cases import get_case, list_cases
    from planning_cli import main
    case=get_case('regulatory-road-plan')
    assert len(list_cases()[0]['available_variants'])==3
    for vid, entities, length in [('oblique-x60',30,515),('oblique-t60',16,400)]:
        output=tmp_path/vid
        assert main(['generate','--case','regulatory-road-plan','--variant',vid,'--out',str(output)])==0
        result=json.loads((output/'result.json').read_text(encoding='utf-8'))
        assert not errors(result)
        assert result['metrics']['entity_count']==entities
        assert result['metrics']['total_centerline_length']==pytest.approx(length)
        tangent_checks(result)
    case['variants'][1]['spec']['roads'][0]['name']='changed'
    assert get_case(case['id'])['spec']['roads'][0]['name']!='changed'
    with pytest.raises(ValueError,match='方案 ID'):
        main(['generate','--variant','typo','--out',str(tmp_path/'invalid')])
    assert not (tmp_path/'invalid').exists()
    with pytest.raises(ValueError,match='同时'):
        main(['generate','--variant','oblique-x60','--spec','unused.json','--out',str(tmp_path/'mixed')])
