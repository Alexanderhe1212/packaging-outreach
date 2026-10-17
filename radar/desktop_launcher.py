"""macOS desktop entry; reuse one local server, never start outreach."""
import fcntl
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = Path.home() / 'Library' / 'Logs' / 'DecisionFinder'
URL = 'http://127.0.0.1:18830'

def healthy():
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(URL+'/api/health', timeout=1) as response:
            return json.load(response) == {'app':'decision-finder','ok':True}
    except Exception:
        return False

def ensure_server():
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/'launcher.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if healthy(): return
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',18830))==0:
                raise RuntimeError('端口 18830 已被其他服务占用；请联系助手检查。')
        with (STATE/'server.log').open('ab') as out:
            child=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'app.py')],cwd=ROOT,
                stdin=subprocess.DEVNULL,stdout=out,stderr=out,start_new_session=True)
        for _ in range(50):
            if healthy(): return
            if child.poll() is not None: break
            time.sleep(.2)
        raise RuntimeError('客户查找服务未能启动，请查看 ~/Library/Logs/DecisionFinder/server.log')

if __name__=='__main__':
    ensure_server()
    if '--check-only' not in sys.argv:
        subprocess.run(['/usr/bin/open',URL],check=True)
