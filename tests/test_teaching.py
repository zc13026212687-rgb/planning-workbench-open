import copy,io,json,zipfile
import pytest
from app.cases import get_case
from app.geometry import generate,export_dxf
from app.store import Store
from app.teaching import compare_jobs,assignment_bytes
from app.rules import review

def test_ab_comparison_reports_actual_diff_and_unknown_cost():
    c=get_case('renewal-street-adjustment')
    a={'id':'a','result':generate(c['variants'][0]['spec'])};b={'id':'b','result':generate(c['variants'][1]['spec'])}
    r=compare_jobs(a,b)
    assert any(x['road_id']=='renewal-branch' for x in r['road_changes'])
    assert r['errors']['A'] and not r['errors']['B']
    assert r['cost'] is None and r['traffic_effect'] is None
    b['result']['spec']['units']='mm'
    with pytest.raises(ValueError):compare_jobs(a,b)

def test_assignment_excludes_credentials_and_contains_process(tmp_path):
    store=Store(tmp_path);spec=get_case('regulatory-road-plan')['spec'];result=generate(spec)
    p=store.put('projects',{'spec':spec,'history':[]})
    j=store.put('jobs',{'id':'j','project_id':p['id'],'status':'succeeded','spec':spec,'result':result,'events':[],'mock':False,'runtime':'builtin','provider':None,'synthetic':True})
    folder=tmp_path/'artifacts/j';folder.mkdir(parents=True);export_dxf(result,folder/'drawing.dxf')
    store.put('providers',{'name':'private','secret':'NEVER-PACK-THIS'})
    data=assignment_bytes(store,'j')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert {'drawing.dxf','parameters.json','process.json','quality.json','revision-history.json','cad-operations.json'}<=set(z.namelist())
        assert not any(b'NEVER-PACK-THIS' in z.read(x) for x in z.namelist())

def test_rule_requires_explicit_context():
    spec={'units':'m','norm_context':{'jurisdiction':'Beijing'},'components':[{'role':'sidewalk','width':1}]}
    assert not any(x['category']=='norm_issue' for x in review(spec))
    spec['norm_context'].update(road_class='branch',general_urban_section=True,new_construction=True,no_high_pedestrian_facility=True,no_transit_entrance_within_50m=True,inside_construction_area=True,no_sparse_pedestrian_side=True)
    assert any(x['category']=='norm_issue' and x['pdf_page']==21 for x in review(spec))
    spec['components'][0]['width']=2.5
    assert any(x['category']=='design_tradeoff' for x in review(spec))
    spec['components'][0]['width']=3
    assert any(x['category']=='norm_checked' for x in review(spec))

def test_interrupted_cad_audit_is_unknown_not_replayed(tmp_path):
    first=Store(tmp_path);first.put('cad_audit',{'id':'in-flight','status':'running','action':'apply','document_id':'d','job_id':'j'})
    second=Store(tmp_path)
    assert second.get('cad_audit','in-flight')['status']=='unknown_after_restart'
