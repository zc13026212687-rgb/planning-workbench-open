"""Original local API for parcel geometry, control indicators and reviewable exports."""
from __future__ import annotations
import json, re, shutil, uuid, zipfile
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse


def finite_json(value, *, max_chars=1_000_000):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('参数必须为有限数值和JSON数据。') from exc
    if max_chars is not None and len(encoded) > max_chars:
        raise ValueError('参数超过当前本地计算上限。')
    return encoded


def export_package(result, folder: Path, *, sheets=True):
    """Write an empty caller-owned folder and retain a precise failure record.

    The 1 MB request limit applies to input, not expanded generated geometry.
    All entities and sheets are checked before the first drawing is written.
    """
    from .parcels import export_parcels_dxf, export_parcels_csv, export_parcels_json, build_control_sheet
    from .cad import validate_entities
    folder=Path(folder)
    finite_json(result,max_chars=None)
    if result['report']['errors']:
        raise ValueError('地块校核存在错误，不能导出。')
    if not folder.is_dir() or folder.is_symlink() or any(folder.iterdir()):
        raise ValueError('导出目录必须是已建立的空目录，不覆盖已有文件。')
    status={'status':'running','stage':'preflight','completed_files':[]}
    status_path=folder/'export-status.json'
    status_path.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')

    def checkpoint():
        status_path.write_text(json.dumps(status,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

    def written(name):
        status['completed_files'].append(name)
        checkpoint()

    def write_json(name,value):
        with (folder/name).open('x',encoding='utf-8') as handle:
            json.dump(value,handle,ensure_ascii=False,indent=2,allow_nan=False)
        written(name)

    sheet_records=[]
    try:
        validate_entities(result['entities'])
        prepared=[]
        if sheets:
            for parcel in result.get('parcels',[]):
                pid=parcel['id']; sheet=build_control_sheet(result,pid)
                if sheet['report']['errors']:
                    raise ValueError(f'图则 {pid} 生成失败，尚未写入图纸。')
                validate_entities(sheet['entities'])
                finite_json(sheet,max_chars=None)
                prepared.append((pid,sheet))
        status['stage']='writing_metadata';checkpoint()
        for name, value in [('parameters',result['spec']),('quality',result['report']),('result',result)]:
            write_json(f'{name}.json',value)
        for name,writer in [('drawing.dxf',export_parcels_dxf),('parcel-indicators.csv',export_parcels_csv),('parcel-data.json',export_parcels_json)]:
            status['stage']=name;checkpoint();writer(result,folder/name);written(name)
        for index,(pid,sheet) in enumerate(prepared,1):
            # IDs are data; filenames use indices so user IDs cannot escape.
            filename=f'sheet-{index:03d}.dxf';data_file=f'sheet-{index:03d}.json'
            status['stage']=filename;checkpoint()
            export_parcels_dxf(sheet,folder/filename);written(filename)
            write_json(data_file,sheet)
            sheet_records.append({'parcel_id':pid,'file':filename,'data_file':data_file,
                'geometry_sha256':sheet['data']['geometry_sha256'],'units':'m',
                'sheet_size_m':sheet['metrics']['sheet_size_m'],
                'map_scale_denominator':sheet['metrics']['map_scale_denominator'],
                'geometry_role':'scaled_sheet_diagram_not_source_coordinates','spec':sheet['spec']})
        if sheets:write_json('sheet-index.json',sheet_records)
        status.update(status='succeeded',stage='complete');checkpoint()
    except Exception as exc:
        status.update(status='failed',error=str(exc)[:1500]);checkpoint()
        raise
    return sheet_records


def register_regulatory_routes(app, root: Path, data: Path, cad):
    artifacts=data/'regulatory'

    def checked(body):
        if not isinstance(body,dict) or not isinstance(body.get('spec'),dict):
            raise ValueError('请提供 spec 参数对象。')
        finite_json(body['spec'])
        from .parcels import generate
        return generate(body['spec'])

    @app.get('/regulatory')
    def page():
        return FileResponse(root/'web/regulatory.html')

    @app.get('/api/regulatory/example')
    def example():
        from .parcels import get_example
        return get_example()

    @app.post('/api/regulatory/preview')
    def preview(body:dict):
        return checked(body)

    @app.post('/api/regulatory/sheet-preview')
    def sheet_preview(body:dict):
        from .parcels import build_control_sheet
        result=checked(body)
        if result['report']['errors']:
            raise ValueError('先修正总图校核错误，再生成图则。')
        pid=body.get('parcel_id')
        if not isinstance(pid,str):raise ValueError('请选择地块编号。')
        return build_control_sheet(result,pid)

    @app.post('/api/regulatory/export')
    def export(body:dict):
        cad_new=body.get('cad_new',False)
        if not isinstance(cad_new,bool):raise ValueError('cad_new须为布尔值。')
        if cad_new and body.get('confirm_cad_new') is not True:
            raise ValueError('CAD落图需明确选择新建独立图纸。')
        result=checked(body)
        if result['report']['errors']:raise ValueError('总图存在阻断错误，未创建导出目录。')
        artifact_id=uuid.uuid4().hex
        folder=artifacts/artifact_id
        folder.mkdir(parents=True,exist_ok=False)
        try:
            sheets=export_package(result,folder)
        except Exception as exc:
            failure={'artifact_id':artifact_id,'status':'failed','path':str(folder.resolve()),
                     'error':str(exc)[:1500],'files':sorted(p.name for p in folder.iterdir() if p.is_file()),
                     'drawing_package_complete':False}
            (folder/'receipt.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2),encoding='utf-8')
            raise HTTPException(500,detail=failure) from exc
        record={'artifact_id':artifact_id,'metrics':result['metrics'],'path':str(folder.resolve()),'sheet_count':len(sheets)}
        if cad_new:
            record['cad']={'status':'starting'}
            try:
                document=cad.new_document();did=document['document_id']
                record['cad'].update(document_id=did,stage='apply')
                applied=cad.apply(did,result['entities'],'regulatory-'+artifact_id,document.get('version'))
                record['cad'].update(applied=applied,stage='save')
                # The shared bridge owns data/cad only; never widen its path guard.
                cad_source=(data/'cad'/f'regulatory-{artifact_id}.dwg').resolve()
                saved=cad.save(did,cad_source)
                record['cad'].update(saved=saved,stage='copy_to_package',source_path=str(cad_source))
                if not cad_source.is_file() or cad_source.stat().st_size==0:
                    raise ValueError('CAD未生成可复制的非空DWG。')
                destination=folder/'drawing.dwg'
                partial_destination=folder/'drawing.dwg.partial'
                with cad_source.open('rb') as source_handle,partial_destination.open('xb') as target_handle:
                    shutil.copyfileobj(source_handle,target_handle)
                if partial_destination.stat().st_size!=cad_source.stat().st_size:
                    raise ValueError('DWG成果复制不完整。')
                partial_destination.rename(destination)
                record['cad'].update(status='saved',stage='complete',package_path=str(destination.resolve()))
            except Exception as exc:
                record['cad'].update(status='failed_or_unknown',error=str(exc)[:1500])
            (folder/'cad-readback.json').write_text(json.dumps(record['cad'],ensure_ascii=False,indent=2),encoding='utf-8')
        record['status']='succeeded' if not cad_new or record['cad']['status']=='saved' else 'partial_success'
        record['drawing_package_complete']=True
        record['files']=sorted({p.name for p in folder.iterdir() if p.is_file()}|{'receipt.json'})
        record['download_url']=f'/api/regulatory/artifacts/{artifact_id}/bundle.zip'
        (folder/'receipt.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        try:
            with zipfile.ZipFile(folder/'bundle.zip','x',zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(folder.iterdir()):
                    if path.is_file() and path.name!='bundle.zip':archive.write(path,path.name)
        except Exception as exc:
            record.update(status='archive_failed',error=str(exc)[:1500])
            record.pop('download_url',None)
            (folder/'receipt.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            raise HTTPException(500,detail=record) from exc
        return record

    @app.get('/api/regulatory/artifacts/{artifact_id}/bundle.zip')
    def download(artifact_id:str):
        if not re.fullmatch(r'[0-9a-f]{32}',artifact_id):raise HTTPException(404,'成果不存在')
        path=artifacts/artifact_id/'bundle.zip'
        if not path.is_file():raise HTTPException(404,'成果不存在')
        receipt=path.parent/'receipt.json'
        if not receipt.is_file() or json.loads(receipt.read_text(encoding='utf-8')).get('status') not in ('succeeded','partial_success'):
            raise HTTPException(409,'成果包未完成；请检查本地导出诊断记录。')
        return FileResponse(path,filename=f'regulatory-{artifact_id[:8]}.zip',media_type='application/zip')
