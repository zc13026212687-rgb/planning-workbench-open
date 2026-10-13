"""Exercise real parcel HTTP/export paths; never start AutoCAD from a unit test."""
import copy
import io
import json
import zipfile
import pytest
import ezdxf
from fastapi.testclient import TestClient
from app import main
from app.parcels import get_example


class NoCad:
    def __init__(self, *args): pass
    def close(self): pass
    def __getattr__(self, key):
        raise AssertionError('Unexpected CAD call: '+key)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'CadBridge', NoCad)
    app=main.create_app(tmp_path, token='regulatory-test')
    with TestClient(app, headers={'x-local-token':'regulatory-test'}) as c:
        yield c, tmp_path
    app.state.jobs.pool.shutdown(wait=True, cancel_futures=True)
    app.state.store.db.close()


def test_preview_and_download_zip_contain_editable_entities(client):
    c, folder=client
    spec=c.get('/api/regulatory/example').json()
    preview=c.post('/api/regulatory/preview',json={'spec':spec})
    assert preview.status_code==200,preview.text
    result=preview.json()
    assert not result['report']['errors']
    assert len(result['parcels'])==4
    spec['attribute_geometry_bindings']=result['geometry_bindings']
    exported=c.post('/api/regulatory/export',json={'spec':spec})
    assert exported.status_code==200,exported.text
    record=exported.json()
    assert record['sheet_count']==4 and 'cad' not in record
    downloaded=c.get(record['download_url'])
    assert downloaded.status_code==200
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as z:
        assert {'drawing.dxf','parcel-indicators.csv','parcel-data.json','sheet-index.json','receipt.json','sheet-001.dxf','sheet-004.dxf'} <= set(z.namelist())
        assert not any(n.endswith('.dwg') for n in z.namelist())
        assert len(json.loads(z.read('sheet-index.json')))==4
        drawing=ezdxf.read(io.StringIO(z.read('drawing.dxf').decode('utf-8'),newline=None))
        assert len(drawing.modelspace().query('POLYLINE LWPOLYLINE'))>4
        assert not drawing.audit().has_errors
        assert json.loads(z.read('result.json'))['geometry_bindings']==result['geometry_bindings']


def test_changed_road_width_cannot_reassign_attributes_or_write_files(client):
    c, folder=client
    spec=get_example()
    preview=c.post('/api/regulatory/preview',json={'spec':spec}).json()
    spec['attribute_geometry_bindings']=preview['geometry_bindings']
    spec['roads'][0]['total_width_m']+=2
    changed=c.post('/api/regulatory/preview',json={'spec':spec}).json()
    assert any(e['code']=='attribute_binding_mismatch' for e in changed['report']['errors'])
    assert c.post('/api/regulatory/export',json={'spec':spec}).status_code==422
    assert not (folder/'regulatory').exists()


def test_unconfirmed_cad_rejected_before_output_creation(client):
    c, folder=client
    response=c.post('/api/regulatory/export',json={'spec':get_example(),'cad_new':True})
    assert response.status_code==422
    assert not (folder/'regulatory').exists()


def test_sheet_keeps_chosen_id_and_unknown_id_fails(client):
    c, folder=client
    response=c.post('/api/regulatory/sheet-preview',json={'spec':get_example(),'parcel_id':'P002'})
    assert response.status_code==200,response.text
    assert response.json()['data']['id']=='P002'
    assert len(response.json()['entities'])>10
    assert c.post('/api/regulatory/sheet-preview',json={'spec':get_example(),'parcel_id':'missing'}).status_code in (404,422)


def test_nonfinite_and_foreign_access_rejected(client):
    c, folder=client
    response=c.post('/api/regulatory/preview',content='{"spec":{"x":NaN}}',headers={'content-type':'application/json'})
    assert response.status_code==422
    assert c.get('/api/regulatory/example',headers={'x-local-token':'wrong'}).status_code==401
    assert c.get('/api/regulatory/artifacts/not-an-id/bundle.zip').status_code==404


def test_cad_failure_is_reported_and_dxf_remains_usable(client):
    c, folder=client
    response=c.post('/api/regulatory/export',json={'spec':get_example(),'cad_new':True,'confirm_cad_new':True})
    assert response.status_code==200,response.text
    record=response.json()
    assert record['cad']['status']=='failed_or_unknown'
    assert 'Unexpected CAD call' in record['cad']['error']
    with zipfile.ZipFile(io.BytesIO(c.get(record['download_url']).content)) as z:
        assert 'drawing.dxf' in z.namelist() and 'cad-readback.json' in z.namelist()
        assert 'drawing.dwg' not in z.namelist()
