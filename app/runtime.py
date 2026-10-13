from __future__ import annotations
import copy, json, re, threading, time, hashlib, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from jsonschema import validate
from .providers import chat_response, Cancelled
from .skills import list_skills,validate_skill_input

TOOLS=[
 {'name':'inspect_project','description':'Read the current user-confirmed road specification and units.','parameters':{'type':'object','properties':{},'additionalProperties':False}},
 {'name':'set_road_parameters','description':'Calculate a reviewable road preview with changed widths / junction radius. Does NOT write to CAD.','parameters':{'type':'object','properties':{'left_width':{'type':'number','exclusiveMinimum':0,'maximum':100},'right_width':{'type':'number','exclusiveMinimum':0,'maximum':100},'junction_radius':{'type':'number','minimum':0,'maximum':100}},'additionalProperties':False}},
 {'name':'calculate_roads','description':'Generate and validate the current road plan as editable CAD entities in a preview. User separately approves actual CAD insertion.','parameters':{'type':'object','properties':{},'additionalProperties':False}},
]

class Jobs:
    def __init__(self,store,root):
        self.store=store;self.root=Path(root);self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='PlanningJob');self.gate=threading.BoundedSemaphore(12);self.cancel_flags={};self.lock=threading.Lock()
    def submit(self,body):
        if not self.gate.acquire(blocking=False): raise ValueError('本地任务队列已满，请等待或取消任务')
        try:
            project=self.store.get('projects',body['project_id'])
            kind=body.get('kind','geometry')
            if kind not in ('geometry','agent'): raise ValueError('不支持的任务类型')
            spec=copy.deepcopy(body.get('spec') or project['spec'])
            if len(json.dumps(spec))>300000: raise ValueError('图纸参数过大')
            profile=None
            if kind=='agent' and body.get('provider_id'):
                profile=self.store.get('providers',body['provider_id'])
            runtime=body.get('runtime','builtin')
            if runtime not in ('builtin','mock','codex'): raise ValueError('未知智能体')
            if kind=='agent' and runtime=='builtin' and not profile: raise ValueError('请选择已配置的模型 API，或明确使用离线教学演示')
            skill=body.get('skill_id') or ('road-cross-section' if spec.get('kind')=='road_cross_section' else 'urban-renewal' if project.get('case_id')=='renewal-street-adjustment' else 'road-plan')
            selected=next((x for x in list_skills(self.root,self.store) if x['id']==skill),None)
            if not selected or not selected['ready'] or not selected['enabled']: raise ValueError('技能未启用或不可执行')
            if selected['executor'] not in ('geometry','section'):raise ValueError('此技能不是图纸生成执行器')
            if (selected['executor']=='section') != (spec.get('kind')=='road_cross_section'):raise ValueError('技能执行器与图纸类型不一致')
            validate_skill_input(selected,spec)
            if spec.get('kind')=='road_cross_section' and kind=='agent' and runtime in ('mock','codex'):raise ValueError('该智能体参数规划尚不支持横断面，请使用组成参数表单')
            job=self.store.put('jobs',{'id':uuid.uuid4().hex,'project_id':project['id'],'kind':kind,'status':'queued','events':[],'result':None,'message':str(body.get('message',''))[:10000],'runtime':runtime,'skill_id':skill,'spec':spec,'provider':({k:profile[k] for k in ('id','name','model','base_url','protocol')} if profile else None),'mock':kind=='agent' and runtime=='mock','usage':None})
            job['synthetic']=project.get('synthetic',True)
            prior=[x for x in self.store.list('jobs') if x.get('project_id')==project['id'] and x['id']!=job['id'] and x.get('kind')=='agent' and x.get('status')=='succeeded'][:3]
            job['context']=[{'request':x.get('message',''),'answer':'\n'.join(str(e['data']) for e in x.get('events',[]) if e.get('type')=='message')[:4000]} for x in reversed(prior)]
            job['input_hash']=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest();self.store.put('jobs',job)
            flag=threading.Event();self.cancel_flags[job['id']]=flag
            self.pool.submit(self.run,job,profile,flag,selected)
            return job
        except Exception:
            self.gate.release();raise
    def cancel(self,id):
        j=self.store.get('jobs',id)
        if j['status'] in ('succeeded','failed','canceled','interrupted'): return j
        if id in self.cancel_flags: self.cancel_flags[id].set()
        return {**j,'cancel_requested':True}
    def run(self,job,profile,cancel,skill):
        if job['spec'].get('kind')=='road_cross_section':
            from .sections import generate,export_section_dxf as export_dxf
        else:
            from .geometry import generate, export_dxf
        active_tools=[t for t in TOOLS if job['spec'].get('kind')!='road_cross_section' or t['name']!='set_road_parameters']
        started=time.monotonic();folder=self.store.folder/'artifacts'/job['id'];folder.mkdir(parents=True,exist_ok=True)
        def emit(kind,data):
            if cancel.is_set(): raise Cancelled('用户取消')
            events=job['events'];events.append({'seq':len(events)+1,'type':kind,'data':copy.deepcopy(data),'elapsed':round(time.monotonic()-started,3)})
            # Keep bounded logs, preserve stable event sequence by refusing runaway runs.
            if len(events)>4000: raise ValueError('任务事件超过上限')
            self.store.put('jobs',job)
        spec=copy.deepcopy(job['spec']);result=None
        try:
            job['status']='running';emit('status','开始执行，输入与配置已固定')
            if job['runtime']=='codex' and job['kind']=='agent':
                from .external import codex_plan
                spec=codex_plan(job['message'],spec,folder,cancel,emit)
                emit('plan','Codex 返回的参数已验证；仅生成预览，CAD 操作仍需确认')
            elif job['kind']=='agent' and job['runtime']=='mock':
                emit('notice','离线规则演示（不是 AI 推理），支持“左宽 N、右宽 N、圆角 N”')
                for field,label in [('left_width','左宽'),('right_width','右宽'),('junction_radius','圆角')]:
                    match=re.search(label+r'\s*[=:：]?\s*(\d+(?:\.\d+)?)',job['message'])
                    if match: spec[field]=float(match[1])
                emit('plan',{'left_width':spec.get('left_width'),'right_width':spec.get('right_width'),'junction_radius':spec.get('junction_radius')})
            elif job['kind']=='agent':
                messages=[{'role':'system','content':'你是控规教学助手。用工具检查并计算当前道路。参数是教学假设，不编造规范或工程结论。只生成可审核预览，不声称已写CAD。工具结果中的错误必须解释。不得执行shell。技能说明：'+skill.get('instructions','')[:7000]}]
                for item in job.get('context',[]):
                    messages.append({'role':'user','content':item['request']})
                    if item['answer']:messages.append({'role':'assistant','content':item['answer']})
                messages.append({'role':'user','content':job['message']})
                usages=[]
                for step in range(6):
                    if cancel.is_set(): raise Cancelled('用户取消')
                    if time.monotonic()-started>240: raise ValueError('智能体超过总时间上限')
                    emit('step',f'模型步骤 {step+1}/6')
                    response=chat_response(profile,messages,active_tools,emit,cancel)
                    usages.append(response['usage']); job['usage']=usages
                    if not response['calls']:
                        emit('message',response['text'] or '模型结束回复')
                        if result is None: emit('notice','模型未调用几何工具，使用当前已确认参数生成预览')
                        break
                    messages.append({'role':'assistant','content':response['text'] or None,'tool_calls':[{'id':c['id'],'type':'function','function':{'name':c['name'],'arguments':c['arguments']}} for c in response['calls']]})
                    for call in response['calls']:
                        definition=next((t for t in active_tools if t['name']==call['name']),None)
                        if not definition: raise ValueError('模型尝试调用未授权工具')
                        validate(call['parsed'],definition['parameters'])
                        emit('tool_call',{'name':call['name'],'arguments':call['parsed'],'tool_call_id':call['id']})
                        if call['name']=='inspect_project': output={'spec':spec,'synthetic':job.get('synthetic',True)}
                        else:
                            if call['name']=='set_road_parameters': spec.update(call['parsed'])
                            validate_skill_input(skill,spec)
                            result=generate(spec);output={'report':result['report'],'metrics':result['metrics'],'entity_count':len(result['entities']),'parameters':{k:spec.get(k) for k in ('left_width','right_width','junction_radius')}}
                        emit('tool_result',output)
                        messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(output,ensure_ascii=False)})
                else: raise ValueError('模型达到工具循环上限，任务停止，未写入CAD')
            if cancel.is_set(): raise Cancelled('用户取消')
            validate_skill_input(skill,spec)
            if result is None: result=generate(spec)
            result['spec']=spec;job['result']=result
            from .rules import annotate
            annotate(result)
            emit('validation',result['report'])
            (folder/'parameters.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
            (folder/'quality.json').write_text(json.dumps(result['report'],ensure_ascii=False,indent=2),encoding='utf-8')
            if result['report'].get('errors'):
                job['status']='failed';job['error']='几何检查存在阻断问题；可查看诊断预览，不能导出或写入 CAD'
            else:
                if cancel.is_set(): raise Cancelled('用户取消')
                export_dxf(result,folder/'drawing.dxf')
                job['status']='succeeded';job['download_url']=f'/api/jobs/{job["id"]}/download.dxf'
            job['duration_seconds']=round(time.monotonic()-started,3)
        except Cancelled:
            job['status']='canceled';job['error']='任务已取消；未执行 CAD 写入'
        except Exception as exc:
            # Provider transport raises sanitized messages; do not expose arbitrary remote bodies.
            job['status']='failed';job['error']=str(exc)[:1500]
        finally:
            job['duration_seconds']=round(time.monotonic()-started,3)
            self.store.put('jobs',job);self.cancel_flags.pop(job['id'],None);self.gate.release()

