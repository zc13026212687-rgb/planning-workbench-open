"""Optional Codex runtime: explicitly selected, read-only, structured plan output."""
from __future__ import annotations
import json,os,subprocess,time
from pathlib import Path
from .providers import Cancelled

def codex_exe():
    root=Path(os.environ.get('APPDATA',''))/'npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
    return root if root.is_file() else None
def runtimes():
    exe=codex_exe()
    return [{'id':'builtin','name':'内置工具型 Agent','status':'ready','description':'使用选定 API，工具仅生成可审核预览'}, {'id':'mock','name':'离线教学规则演示','status':'ready','mock':True,'description':'支持左宽/右宽/圆角参数，不是真实 AI'}, {'id':'codex','name':'Codex CLI（只读规划）','status':'discovered' if exe else 'unavailable','available':bool(exe),'verified':False,'description':'使用 CLI 自身授权与模型；与 API 配置独立。真实调用待用户主动启用。'}]

def codex_plan(message,spec,folder,cancel,emit):
    exe=codex_exe()
    if not exe: raise ValueError('未找到受支持的 Codex CLI')
    schema={'type':'object','properties':{'left_width':{'type':'number','exclusiveMinimum':0,'maximum':100},'right_width':{'type':'number','exclusiveMinimum':0,'maximum':100},'junction_radius':{'type':'number','minimum':0,'maximum':100},'explanation':{'type':'string'}},'required':['left_width','right_width','junction_radius','explanation'],'additionalProperties':False}
    schemafile=folder/'plan-schema.json';outfile=folder/'codex-plan.json';schemafile.write_text(json.dumps(schema),encoding='utf-8')
    prompt='仅根据下面的当前参数与用户需求生成结构化教学道路参数。不执行命令，不操作CAD，不读取其他文件。不能编造工程规范。\n当前参数：'+json.dumps({k:spec.get(k) for k in ('units','left_width','right_width','junction_radius')},ensure_ascii=False)+'\n用户需求：'+message
    cmd=[str(exe),'exec','--ignore-user-config','--sandbox','read-only','--skip-git-repo-check','--ephemeral','--json','--output-schema',str(schemafile),'-o',str(outfile),'-C',str(folder),'-']
    log=open(folder/'codex-events.jsonl','w',encoding='utf-8');err=open(folder/'codex-stderr.txt','w',encoding='utf-8')
    process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=log,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        process.stdin.write(prompt.encode('utf-8'));process.stdin.close();start=time.monotonic()
        emit('runtime','Codex CLI 已启动：read-only，独立任务目录；未直接操作 CAD')
        while process.poll() is None:
            if cancel.is_set(): raise Cancelled()
            if time.monotonic()-start>240: raise ValueError('Codex 运行超时')
            time.sleep(.15)
        if process.returncode!=0 or not outfile.exists(): raise ValueError('Codex 未返回有效结果；请检查 CLI 自身授权或任务诊断')
        from jsonschema import validate
        plan=json.loads(outfile.read_text(encoding='utf-8'));validate(plan,schema)
        emit('message',plan['explanation'])
        return {**spec,**{k:plan[k] for k in ('left_width','right_width','junction_radius')}}
    finally:
        if process.poll() is None:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        log.close();err.close()
