from app.cases import get_case
from app.geometry import generate

def test_geographic_coordinates_never_treated_as_meters():
    spec=get_case('regulatory-road-plan')['spec']
    spec['coordinate_reference']='EPSG:4326'
    result=generate(spec)
    assert any(e['code']=='unsupported_crs' for e in result['report']['errors'])
