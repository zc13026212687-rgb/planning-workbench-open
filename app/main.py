from __future__ import annotations
import asyncio,copy,json,os,secrets,threading,uuid
from pathlib import Path
from urllib.parse import urlparse
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException,Request,UploadFile,File
from fastapi.responses import FileResponse,JSONResponse,StreamingResponse,Response
from fastapi.staticfiles import StaticFiles
from .store import Store
from .providers import public_profile,save_profile,chat_response,ProviderError
from .runtime import Jobs
from .skills import list_skills,diagnose_skill,toggle_skill
from .external import runtimes
from .cad import CadBridge,CadError

ROOT=Path(__file__).resolve().parent.parent
VERSION='0.2.0'

def create_app(data_dir=None,token=None):
    data=Path(data_dir or os.environ.get('PLANNING_DATA_DIR',ROOT/'data')).resolve()
    store=Store(data);jobs=Jobs(store,ROOT);cad=CadBridge(data/'cad')
    local_token=token or os.environ.get('PLANNING_LOCAL_TOKEN') or secrets.token_urlsafe(32)
    @asynccontextmanager
    async def lifespan(app):
        yield
        for event in list(jobs.cancel_flags.values()):event.set()
        jobs.pool.shutdown(wait=False,cancel_futures=True)
        cad.close()
    app=FastAPI(title='清规AI · PlanningWorkbench Open 0.2.0',lifespan=lifespan)
    app.state.store=store;app.state.jobs=jobs;app.state.cad=cad;app.state.token=local_token
    @app.middleware('http')
    async def local_boundary(request:Request,call_next):
        hostname=request.url.hostname
        if hostname not in ('127.0.0.1','localhost','::1','testserver'):
            return JSONResponse({'detail':'仅允许本机访问'},403)
        origin=request.headers.get('origin')
        if origin:
            u=urlparse(origin)
            if u.hostname!=hostname or u.port!=request.url.port or u.scheme!=request.url.scheme:
                return JSONResponse({'detail':'拒绝跨来源请求'},403)
        if request.url.path.startswith('/api/'):
            supplied=request.headers.get('x-local-token') or request.cookies.get('planning_session','')
            if not secrets.compare_digest(str(supplied),local_token):return JSONResponse({'detail':'本机会话失效，请从桌面入口重新打开'},401)
        try: content_length=int(request.headers.get('content-length','0') or 0)
        except ValueError: return JSONResponse({'detail':'无效请求长度'},400)
        if content_length<0: return JSONResponse({'detail':'无效请求长度'},400)
        if content_length>20*1024*1024:
            return JSONResponse({'detail':'请求超过 20MB 本地限制'},413)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='no-referrer'
        if request.headers.get('x-local-token')==local_token:
            response.set_cookie('planning_session',local_token,httponly=True,samesite='strict')
        if request.url.path.startswith('/api/'): response.headers['Cache-Control']='no-store'
        return response
    @app.exception_handler(KeyError)
    async def missing(request,exc):return JSONResponse({'detail':'记录不存在'},404)
    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse({'detail':str(exc)[:2000]},422)
    @app.exception_handler(CadError)
    async def cad_error(request,exc):return JSONResponse({'detail':str(exc)[:2000]},409)
    @app.exception_handler(ProviderError)
    async def provider_error(request,exc):return JSONResponse({'detail':str(exc)},502)
    @app.get('/health')
    def health():return {'status':'ok','application':'planning-workbench','version':VERSION}
    @app.get('/api/bootstrap')
    def bootstrap():
        from .cases import list_cases
        return {'version':VERSION,'cases':list_cases(),'skills':list_skills(ROOT,store),'providers':[public_profile(p) for p in store.list('providers')],'runtimes':runtimes(),'projects':store.list('projects'),'jobs':store.list('jobs')[:100],'cad':cad.status(),'offline':True}
    @app.get('/api/cases/{id}')
    def case(id:str):
        from .cases import get_case
        return get_case(id)
    @app.get('/api/projects')
    def projects():return store.list('projects')
    @app.post('/api/projects')
    def create_project(body:dict):
        from .cases import get_case
        case_id=body.get('case_id','regulatory-road-plan');spec=body.get('spec') or get_case(case_id)['spec']
        return store.put('projects',{'name':str(body.get('name','未命名教学项目'))[:100],'case_id':case_id,'spec':spec,'revision':1,'history':[],'synthetic':body.get('synthetic',True)})
    @app.get('/api/projects/{id}')
    def project(id:str):return store.get('projects',id)
    @app.put('/api/projects/{id}')
    def update_project(id:str,body:dict):
        p=store.get('projects',id)
        if body.get('revision',p['revision'])!=p['revision']:raise HTTPException(409,'方案版本已变，请刷新')
        p['history'].append({'revision':p['revision'],'spec':p['spec']});p['history']=p['history'][-25:]
        p['spec']=body.get('spec',p['spec']);p['name']=body.get('name',p['name']);p['revision']+=1
        return store.put('projects',p)
    @app.get('/api/providers')
    def profiles():return [public_profile(p) for p in store.list('providers')]
    @app.post('/api/providers')
    def profile_save(body:dict):return save_profile(store,body)
    @app.delete('/api/providers/{id}')
    def profile_delete(id:str):store.delete('providers',id);return {'deleted':True}
    @app.post('/api/providers/{id}/test')
    def profile_test(id:str):
        p=store.get('providers',id)
        result=chat_response(p,[{'role':'user','content':'Reply with OK.'}],[],lambda *a:None,threading.Event())
        p['verification']='text_tested';store.put('providers',p)
        return {'status':'text_tested','message':'真实文本请求成功；工具调用尚需任务验证','text':result['text'][:500],'usage':result['usage']}
    @app.get('/api/skills')
    def skills():return list_skills(ROOT,store)
    @app.get('/api/library')
    def library(q:str='',limit:int=30):
        from .library import search
        return search(ROOT,data,q,limit)
    @app.post('/api/skills/{id}/toggle')
    def toggle(id:str,body:dict):
        return toggle_skill(ROOT,store,id,body.get('enabled'))
    @app.post('/api/skills/{id}/diagnose')
    def skill_diagnose(id:str):return diagnose_skill(ROOT,store,id)
    @app.post('/api/mcp/diagnostic')
    def mcp_diagnostic():
        from .mcp_client import run_builtin_diagnostic
        return run_builtin_diagnostic()
    @app.post('/api/jobs')
    def submit(body:dict):return jobs.submit(body)
    @app.get('/api/jobs')
    def list_jobs():return store.list('jobs')[:100]
    @app.get('/api/jobs/{id}')
    def job(id:str):return store.get('jobs',id)
    @app.post('/api/jobs/{id}/cancel')
    def cancel(id:str):return jobs.cancel(id)
    @app.get('/api/jobs/{id}/events')
    async def events(id:str,after:int=0):
        store.get('jobs',id)
        async def stream():
            cursor=after
            while True:
                j=store.get('jobs',id)
                for e in j['events']:
                    if e['seq']>cursor:
                        yield f'id: {e["seq"]}\ndata: {json.dumps(e,ensure_ascii=False)}\n\n';cursor=e['seq']
                if j['status'] in ('succeeded','failed','canceled','interrupted'):
                    yield f'event: complete\ndata: {json.dumps({"status":j["status"]})}\n\n';return
                yield ': heartbeat\n\n';await asyncio.sleep(.5)
        return StreamingResponse(stream(),media_type='text/event-stream')
    @app.get('/api/jobs/{id}/download.dxf')
    def download(id:str):
        j=store.get('jobs',id)
        if j['status']!='succeeded':raise HTTPException(409,'任务未通过校核')
        path=data/'artifacts'/j['id']/'drawing.dxf'
        if not path.is_file():raise HTTPException(404,'图纸产物不存在，请重新生成')
        return FileResponse(path,filename=f'Planning-{id[:8]}.dxf',media_type='application/dxf')
    @app.get('/api/jobs/{id}/report')
    def report(id:str):
        j=store.get('jobs',id)
        return {'job_id':id,'status':j['status'],'spec':(j.get('result') or {}).get('spec',j['spec']),'report':(j.get('result') or {}).get('report'),'events':j['events'],'provider':j['provider'],'mock':j['mock']}
    @app.get('/api/jobs/{id}/assignment.zip')
    def assignment(id:str):
        from .teaching import assignment_bytes
        return Response(assignment_bytes(store,id),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="Assignment-{id[:8]}.zip"'})
    @app.get('/api/compare')
    def compare(a:str,b:str):
        from .teaching import compare_jobs
        return compare_jobs(store.get('jobs',a),store.get('jobs',b))
    @app.get('/api/cad/audit')
    def cad_audit():return store.list('cad_audit')[:100]
    @app.post('/api/import/dxf')
    async def import_file(file:UploadFile=File(...)):
        from .geometry import import_dxf
        if not (file.filename or '').lower().endswith('.dxf'):raise ValueError('首版仅支持 DXF')
        folder=data/'imports';folder.mkdir(exist_ok=True);path=folder/(uuid.uuid4().hex+'.dxf')
        size=0
        with path.open('wb') as f:
            while chunk:=await file.read(65536):
                size+=len(chunk)
                if size>20*1024*1024:raise ValueError('图纸超过 20MB')
                f.write(chunk)
        try: spec=import_dxf(path)
        except Exception:raise ValueError('无法解析该 DXF，请检查版本、单位与中心线实体') from None
        return {'spec':spec,'filename':file.filename,'synthetic':False}
    @app.get('/api/cad/status')
    def cad_status():return cad.status()
    @app.get('/api/cad/inspect')
    def cad_inspect():return cad.inspect_active()
    @app.post('/api/cad/import-centerlines')
    def import_centerlines(body:dict):
        from .cad_import import from_inspection
        return from_inspection(cad.inspect_active(),confirmed_centerlines=body.get('confirmed_centerlines') is True)
    @app.post('/api/cad/new')
    def cad_new():return cad.new_document()
    @app.get('/api/cad/document')
    def cad_document(document_id:str):return cad.read_document(document_id)
    def ready_result(body):
        j=store.get('jobs',body['job_id'])
        if j['status']!='succeeded' or not j['result'] or j['result']['report'].get('errors'):raise ValueError('仅已通过校核的图纸可写入CAD')
        if j['result']['spec'].get('units')!='m':raise ValueError('当前CAD测试图纸单位为米，请先转换项目单位；禁止仅修改单位标签')
        return j
    def audited(action,body,call):
        record={'action':action,'document_id':body.get('document_id'),'job_id':body.get('job_id'),'expected_version':body.get('expected_version'),'status':'running'}
        store.put('cad_audit',record)
        try:
            result=call();record.update(status='completed',result=result);store.put('cad_audit',record);return result
        except Exception as exc:
            record.update(status='failed_or_unknown',error=str(exc)[:1000]);store.put('cad_audit',record);raise
    @app.post('/api/cad/apply')
    def cad_apply(body:dict):
        j=ready_result(body)
        return audited('apply',body,lambda:cad.apply(body['document_id'],j['result']['entities'],j['id'],body.get('expected_version')))
    @app.post('/api/cad/modify')
    def cad_modify(body:dict):
        j=ready_result(body)
        return audited('modify',body,lambda:cad.modify(body['document_id'],j['result']['entities'],j['id'],body.get('expected_version')))
    @app.post('/api/cad/undo')
    def cad_undo(body:dict):return audited('undo',body,lambda:cad.undo(body['document_id']))
    @app.post('/api/cad/save')
    def cad_save(body:dict):
        return audited('save',body,lambda:cad.save(body['document_id'],data/'cad'/f'planning-{uuid.uuid4().hex[:12]}.dwg'))
    @app.post('/api/cad/fit')
    def cad_fit(body:dict):return cad.fit(body['document_id'])
    @app.post('/api/shutdown')
    def shutdown():
        # Desktop launcher observes this flag and only stops its own backend.
        app.state.shutdown_requested=True
        return {'shutdown_requested':True}
    @app.get('/')
    def index():
        path=ROOT/'web/dist/index.html'
        if not path.exists():return JSONResponse({'detail':'前端未构建，请运行本地构建脚本'},503)
        return FileResponse(path)
    from .regulatory_api import register_regulatory_routes
    register_regulatory_routes(app,ROOT,data,cad)
    if (ROOT/'web/dist/assets').exists():app.mount('/assets',StaticFiles(directory=ROOT/'web/dist/assets'),name='assets')
    return app

