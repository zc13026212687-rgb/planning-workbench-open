"""Provider transport. Secrets are Windows DPAPI protected, never returned to UI."""
from __future__ import annotations
import base64, json, re, threading
from urllib.parse import urlparse
import httpx

class Cancelled(Exception): pass
class ProviderError(Exception): pass

def protect(value):
    import win32crypt
    return base64.b64encode(win32crypt.CryptProtectData(json.dumps(value).encode(), 'PlanningStudio', None,None,None,0)).decode()
def unprotect(value):
    if not value: return {'api_key':'','headers':{}}
    import win32crypt
    return json.loads(win32crypt.CryptUnprotectData(base64.b64decode(value),None,None,None,0)[1])
def public_profile(profile):
    return {k:v for k,v in profile.items() if k not in ('secret','api_key','headers')}
def save_profile(store, body):
    p=dict(body); old={}
    if p.get('id'):
        try: old=store.get('providers',p['id'])
        except KeyError: pass
    protocol=p.get('protocol',old.get('protocol','chat_completions'))
    if protocol not in ('chat_completions','responses'): raise ValueError('尚不支持该协议')
    url=p.get('base_url',old.get('base_url','')).strip().rstrip('/'); parsed=urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('API 地址必须是无凭据、无查询参数的 HTTP(S) 地址')
    if parsed.scheme=='http' and parsed.hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('远端模型地址必须使用 HTTPS；HTTP 仅供本机服务')
    secrets=unprotect(old.get('secret'))
    if 'api_key' in p and p['api_key'] is not None:
        if not isinstance(p['api_key'],str) or '\r' in p['api_key'] or '\n' in p['api_key']:
            raise ValueError('API key 必须是不含换行的字符串')
        secrets['api_key']=p['api_key']
    if 'headers' in p and p['headers'] is not None:
        if not isinstance(p['headers'],dict): raise ValueError('headers 必须为对象')
        for k,v in p['headers'].items():
            if not isinstance(k,str) or not re.fullmatch(r'[A-Za-z0-9-]+',k) or not isinstance(v,str) or '\n' in v or '\r' in v: raise ValueError('请求头格式无效')
        secrets['headers']=p['headers']
    result={k:v for k,v in old.items() if k not in ('secret','api_key','headers')}
    result.update({k:p[k] for k in ('id','name','model') if k in p})
    if not result.get('name') or not result.get('model'): raise ValueError('请填写配置名和模型 ID')
    result.update(protocol=protocol,base_url=url,timeout=min(300,max(5,float(p.get('timeout',old.get('timeout',120))))),has_key=bool(secrets.get('api_key')),header_names=list(secrets.get('headers',{})),verification='not_tested')
    result['secret']=protect(secrets)
    store.put('providers',result)
    return public_profile(result)

def endpoint(profile):
    base=profile['base_url'].rstrip('/'); leaf='responses' if profile['protocol']=='responses' else 'chat/completions'
    if base.endswith('/'+leaf): return base
    return base+'/'+leaf

def sse_packets(response, cancel):
    lines=[]
    for line in response.iter_lines():
        if cancel.is_set(): raise Cancelled('用户取消')
        if not line:
            if lines:
                raw='\n'.join(lines); lines=[]
                if raw=='[DONE]': return
                try: yield json.loads(raw)
                except json.JSONDecodeError: raise ProviderError('模型返回无效流事件')
        elif line.startswith('data:'): lines.append(line[5:].lstrip())
    if lines and lines!=['[DONE]']:
        try: yield json.loads('\n'.join(lines))
        except json.JSONDecodeError: raise ProviderError('模型流未完整结束')

def chat_response(profile, messages, tools, emit, cancel):
    if cancel.is_set(): raise Cancelled('用户取消')
    secret=unprotect(profile.get('secret')); headers={'Content-Type':'application/json',**secret.get('headers',{})}
    if secret.get('api_key'): headers['Authorization']='Bearer '+secret['api_key']
    if profile['protocol']=='chat_completions':
        payload={'model':profile['model'],'messages':messages,'stream':True,'stream_options':{'include_usage':True}}
        if tools: payload['tools']=[{'type':'function','function':t} for t in tools]
    else:
        inputs=[]
        for m in messages:
            if m['role']=='tool': inputs.append({'type':'function_call_output','call_id':m['tool_call_id'],'output':m['content']})
            elif m.get('tool_calls'):
                if m.get('content'): inputs.append({'role':'assistant','content':m['content']})
                inputs.extend({'type':'function_call','call_id':t['id'],'name':t['function']['name'],'arguments':t['function']['arguments']} for t in m['tool_calls'])
            else: inputs.append({'role':m['role'],'content':m['content']})
        payload={'model':profile['model'],'input':inputs,'stream':True,'store':False}
        if tools: payload['tools']=[{'type':'function',**t} for t in tools]
    chunks=[]; calls={}; usage=None; finished=False
    try:
        # No automatic replay: a partially consumed stream can already contain tool intent.
        with httpx.Client(timeout=httpx.Timeout(profile['timeout'],connect=10),follow_redirects=False,trust_env=False) as client:
            if cancel.is_set(): raise Cancelled('用户取消')
            with client.stream('POST',endpoint(profile),json=payload,headers=headers) as response:
                if response.status_code>=300:
                    code=response.status_code
                    labels={401:'身份验证失败',402:'余额不足',403:'无访问权限',429:'上游限流'}
                    raise ProviderError(f'{labels.get(code,"模型服务请求失败")} (HTTP {code})；未自动重放')
                for packet in sse_packets(response,cancel):
                    if not isinstance(packet,dict): raise ProviderError('模型流事件必须为对象')
                    if profile['protocol']=='chat_completions':
                        if packet.get('error'): raise ProviderError('模型流返回错误')
                        if packet.get('usage'): usage=packet['usage']
                        for choice in packet.get('choices',[]):
                            reason=choice.get('finish_reason')
                            if reason in ('length','content_filter'): raise ProviderError('模型输出被截断或过滤，未执行工具')
                            if reason: finished=True
                            delta=choice.get('delta',{}); part=delta.get('content')
                            if part: chunks.append(part); emit('token',part)
                            for t in delta.get('tool_calls',[]):
                                i=t.get('index',0); c=calls.setdefault(i,{'id':'','name':'','arguments':''})
                                if t.get('id'): c['id']=t['id']
                                f=t.get('function',{}); c['name']+=f.get('name',''); c['arguments']+=f.get('arguments','')
                    else:
                        typ=packet.get('type','')
                        if typ=='response.output_text.delta':
                            chunks.append(packet.get('delta','')); emit('token',packet.get('delta',''))
                        if typ=='response.output_item.added' and packet.get('item',{}).get('type')=='function_call':
                            it=packet['item']; calls[packet['output_index']]={'id':it['call_id'],'name':it['name'],'arguments':it.get('arguments','')}
                        if typ=='response.function_call_arguments.delta':
                            c=calls.setdefault(packet['output_index'],{'id':'','name':'','arguments':''}); c['arguments']+=packet.get('delta','')
                        if typ=='response.function_call_arguments.done':
                            c=calls.setdefault(packet['output_index'],{'id':'','name':'','arguments':''}); c['arguments']=packet.get('arguments',c['arguments'])
                        if typ=='response.output_item.done' and packet.get('item',{}).get('type')=='function_call':
                            it=packet['item']; calls[packet['output_index']]={'id':it['call_id'],'name':it['name'],'arguments':it['arguments']}
                        if typ=='response.completed':
                            final=packet.get('response',{})
                            if final.get('status') not in (None,'completed'): raise ProviderError('Responses 任务未正常完成')
                            usage=final.get('usage'); finished=True
                            # Final output is authoritative when supplied, including
                            # the standard item id versus tool call id distinction.
                            for index,it in enumerate(final.get('output',[])):
                                if it.get('type')=='function_call':
                                    calls[index]={'id':it.get('call_id',''),'name':it.get('name',''),'arguments':it.get('arguments','')}
                        if typ in ('error','response.failed','response.incomplete'): raise ProviderError('Responses 任务未正常完成')
    except (httpx.TimeoutException,httpx.NetworkError,httpx.RemoteProtocolError):
        if cancel.is_set(): raise Cancelled('用户取消') from None
        raise ProviderError('模型网络中断或超时；已停止，未重放工具操作') from None
    if cancel.is_set(): raise Cancelled('用户取消')
    if not finished: raise ProviderError('模型流未收到完成事件')
    for c in calls.values():
        if not c['id'] or not c['name']: raise ProviderError('工具调用标识缺失')
        try: c['parsed']=json.loads(c['arguments'])
        except json.JSONDecodeError: raise ProviderError('工具参数不是完整 JSON')
        if not isinstance(c['parsed'],dict): raise ProviderError('工具参数必须是 JSON 对象')
    if len({c['id'] for c in calls.values()})!=len(calls): raise ProviderError('工具调用标识重复')
    return {'text':''.join(chunks),'calls':list(calls.values()),'usage':usage}
