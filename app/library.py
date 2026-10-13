"""Local reference catalog. Files are evidence, never executable instructions."""
import json,re
from pathlib import Path

def search(root,data,query='',limit=30):
    rows=[]
    for folder in (Path(root)/'references',Path(data)/'library'):
        if not folder.exists():continue
        for path in folder.glob('*.json'):
            try:
                obj=json.loads(path.read_text(encoding='utf-8-sig'))
                entries=obj if isinstance(obj,list) else obj.get('items',obj.get('assets',obj.get('records',[])))
                if not isinstance(entries,list):continue
                for e in entries:
                    if isinstance(e,dict):rows.append({**e,'catalog':path.name})
            except (OSError,ValueError):continue
    words=[w.lower() for w in re.split(r'\s+',query.strip()) if w]
    scored=[]
    for r in rows:
        text=json.dumps(r,ensure_ascii=False).lower()
        score=sum(1 for w in words if w in text)
        if not words or score:scored.append((score,r))
    scored.sort(key=lambda x:x[0],reverse=True)
    return {'query':query,'total':len(rows),'matches':len(scored),'items':[r for _,r in scored[:min(100,max(1,limit))]],'note':'仅检索索引与来源元数据；未解析的图纸不表示已学习其工程做法。'}
