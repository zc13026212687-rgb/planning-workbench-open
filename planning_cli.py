"""Standalone entry: same deterministic engine and CAD adapter as the desktop."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main(argv=None):
    p=argparse.ArgumentParser(description='规绘独立规划 CAD 技能（与桌面共用引擎）')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('cases')
    q=sub.add_parser('library');q.add_argument('query',nargs='?',default='');q.add_argument('--limit',type=int,default=20)
    g=sub.add_parser('generate');g.add_argument('--case',default='regulatory-road-plan');g.add_argument('--spec',type=Path);g.add_argument('--out',type=Path,required=True);g.add_argument('--cad-new',action='store_true',help='明确授权在本机CAD新图纸落图，不修改已有图纸')
    g.add_argument('--variant',help='案例方案 ID，如 oblique-x60 / oblique-t60；不能与 --spec 同用')
    v=sub.add_parser('validate');v.add_argument('--spec',type=Path,required=True)
    s=sub.add_parser('sheet');s.add_argument('--spec',type=Path,required=True);s.add_argument('--parcel',required=True);s.add_argument('--out',type=Path,required=True);s.add_argument('--cad-new',action='store_true')
    a=p.parse_args(argv)
    if a.command=='cases':
        from app.cases import list_cases
        print(json.dumps(list_cases(),ensure_ascii=False,indent=2));return 0
    if a.command=='library':
        from app.library import search
        print(json.dumps(search(ROOT,ROOT/'data',a.query,a.limit),ensure_ascii=False,indent=2));return 0
    from app.cases import get_case
    if a.spec and getattr(a,'variant',None):raise ValueError('--spec 与 --variant 不能同时使用，避免输入来源不明确')
    if a.spec:spec=json.loads(a.spec.read_text(encoding='utf-8-sig'))
    else:
        case=get_case(a.case)
        if a.variant:
            variant=next((v for v in case.get('variants',[]) if v['id']==a.variant),None)
            if variant is None:raise ValueError('案例中没有该方案 ID：'+a.variant)
            spec=variant['spec']
        else:spec=case['spec']
    if not isinstance(spec,dict):raise ValueError('spec 必须为JSON对象。')
    from app.regulatory_api import finite_json
    finite_json(spec)
    if spec.get('kind')=='regulatory_parcels':
        from app.parcels import generate,export_parcels_dxf as export_dxf
    elif spec.get('kind')=='road_cross_section':
        from app.sections import generate,export_section_dxf as export_dxf
    else:
        from app.geometry import generate,export_dxf
    result=generate(spec)
    from app.rules import annotate
    annotate(result)
    if a.command=='validate':
        print(json.dumps({'report':result['report'],'metrics':result['metrics']},ensure_ascii=False,indent=2,allow_nan=False));return 2 if result['report']['errors'] else 0
    if a.command=='sheet':
        if spec.get('kind')!='regulatory_parcels':raise ValueError('图则输入须为regulatory_parcels。')
        if result['report']['errors']:
            print(json.dumps({'status':'failed','report':result['report']},ensure_ascii=False));return 2
        from app.parcels import build_control_sheet
        result=build_control_sheet(result,a.parcel)
        spec=result['spec']
    if a.out.exists():raise ValueError('输出目录已存在；请用新目录保留历史')
    if a.cad_new and spec.get('units')!='m':raise ValueError('CAD桥目前仅接受米，不能仅改单位标签')
    a.out.mkdir(parents=True)
    record={'status':'running','command':a.command,'output':str(a.out.resolve()),'stage':'export'}

    def write_json(name,value):
        with (a.out/name).open('x',encoding='utf-8') as handle:
            json.dump(value,handle,ensure_ascii=False,indent=2,allow_nan=False)

    def finish(status,exit_code):
        record.update(status=status,metrics=result['metrics'])
        record['files']=sorted({path.name for path in a.out.iterdir() if path.is_file()}|{'receipt.json'})
        write_json('receipt.json',record)
        print(json.dumps(record,ensure_ascii=False,allow_nan=False))
        return exit_code

    try:
        if a.command=='generate' and spec.get('kind')=='regulatory_parcels' and not result['report']['errors']:
            from app.regulatory_api import export_package
            # export_package requires an empty directory and owns its metadata.
            records=export_package(result,a.out)
            record['sheet_count']=len(records)
        else:
            for name,value in [('parameters',spec),('quality',result['report']),('result',result)]:
                write_json(name+'.json',value)
            if result['report']['errors']:
                record.update(stage='validation',report=result['report'])
                return finish('validation_failed',2)
            if a.command=='sheet':
                metadata={'parcel_id':a.parcel,'geometry_sha256':result['data']['geometry_sha256'],
                    'units':'m','sheet_size_m':result['metrics']['sheet_size_m'],
                    'map_scale_denominator':result['metrics']['map_scale_denominator'],
                    'geometry_role':'scaled_sheet_diagram_not_source_coordinates',
                    'source_parameters':'parameters.json','complete_sheet_result':'result.json'}
                write_json('sheet-metadata.json',metadata)
                record['sheet']=metadata
            export_dxf(result,a.out/'drawing.dxf')
        record['drawing_package_complete']=True
        if a.cad_new:
            from app.cad import CadBridge
            bridge=None
            cad_record={'status':'starting','stage':'initialize_bridge'}
            try:
                bridge=CadBridge(a.out.resolve())
                cad_record['stage']='new_document'
                doc=bridge.new_document();did=doc['document_id']
                cad_record.update(document_id=did,stage='apply')
                applied=bridge.apply(did,result['entities'],'standalone-initial',doc.get('version'))
                cad_record.update(applied=applied,stage='save')
                saved=bridge.save(did,a.out.resolve()/'drawing.dwg')
                cad_record.update(status='saved',stage='complete',saved=saved)
            except Exception as exc:
                cad_record.update(status='failed_or_unknown',error=str(exc)[:1500])
            finally:
                if bridge is not None:
                    try:bridge.close()
                    except Exception as exc:cad_record['bridge_release_warning']=str(exc)[:1500]
            write_json('cad-readback.json',cad_record)
            record['cad']=cad_record
            if cad_record['status']!='saved':
                record['stage']='cad'
                return finish('partial_success',3)
        record['stage']='complete'
        return finish('succeeded',0)
    except Exception as exc:
        record.update(error=str(exc)[:1500],error_type=type(exc).__name__)
        return finish('partial_failure',1)

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr,'reconfigure'):sys.stderr.reconfigure(encoding='utf-8')
    try:sys.exit(main())
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(1)
