"""Loopback-only server entrypoint, emits launch metadata into the local data directory."""
import argparse,asyncio,json,os,secrets,socket,threading,time,sys
from pathlib import Path
import uvicorn
from app.main import create_app,ROOT

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=0);args=parser.parse_args()
    data=Path(os.environ.get('PLANNING_DATA_DIR',ROOT/'data'));data.mkdir(exist_ok=True,parents=True)
    if sys.stdout is None:sys.stdout=open(data/'backend.log','a',encoding='utf-8',buffering=1)
    if sys.stderr is None:sys.stderr=sys.stdout
    token=secrets.token_urlsafe(32);app=create_app(data,token)
    sock=socket.socket();sock.bind(('127.0.0.1',args.port));sock.listen(128);port=sock.getsockname()[1]
    state={'pid':os.getpid(),'port':port,'url':f'http://127.0.0.1:{port}/#token={token}','token':token,'application':'planning-workbench','root':str(ROOT.resolve())}
    statefile=data/'server.json';statefile.write_text(json.dumps(state),encoding='utf-8')
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning',access_log=False))
    def monitor():
        while not server.should_exit:
            if getattr(app.state,'shutdown_requested',False):server.should_exit=True;return
            time.sleep(.2)
    threading.Thread(target=monitor,daemon=True).start()
    try:server.run(sockets=[sock])
    finally:
        try:
            if json.loads(statefile.read_text())['pid']==os.getpid():statefile.unlink()
        except (OSError,ValueError):pass
if __name__=='__main__':main()
