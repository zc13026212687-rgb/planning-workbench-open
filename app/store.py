from __future__ import annotations
import json, sqlite3, threading, uuid
from pathlib import Path
from datetime import datetime, timezone

def now():
    return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self, folder: Path):
        self.folder=Path(folder); self.folder.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.db=sqlite3.connect(self.folder/'workbench.sqlite3',check_same_thread=False)
        self.db.execute('pragma journal_mode=WAL')
        self.db.execute('create table if not exists objects(kind text, id text, body text, primary key(kind,id))')
        self.db.commit()
        for j in self.list('jobs'):
            if j['status'] in ('queued','running','waiting_for_input'):
                j['status']='interrupted'; j['error']='应用重启，任务已中断；原有图纸未自动重放。'; self.put('jobs',j)
        for a in self.list('cad_audit'):
            if a.get('status')=='running':
                a['status']='unknown_after_restart';a['error']='退出前未收到CAD完成确认，须重新读取图纸判断实际结果，不能自动重放。';self.put('cad_audit',a)
    def put(self,kind,obj):
        with self.lock:
            obj.setdefault('id',uuid.uuid4().hex); obj.setdefault('created_at',now()); obj['updated_at']=now()
            self.db.execute('insert or replace into objects values(?,?,?)',(kind,obj['id'],json.dumps(obj,ensure_ascii=False,allow_nan=False)))
            self.db.commit()
        return obj
    def get(self,kind,id):
        with self.lock:
            r=self.db.execute('select body from objects where kind=? and id=?',(kind,id)).fetchone()
        if not r: raise KeyError(id)
        return json.loads(r[0])
    def list(self,kind):
        with self.lock:
            rows=self.db.execute('select body from objects where kind=? order by rowid desc',(kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def delete(self,kind,id):
        with self.lock:
            self.db.execute('delete from objects where kind=? and id=?',(kind,id)); self.db.commit()
