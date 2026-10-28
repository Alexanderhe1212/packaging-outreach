"""Customer bundled runtime. Own services only; opening never starts outreach."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent

def environment():
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'UserRadarCustomer'
    base.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # Never inherit a developer's data directory or credentials.
    for key in list(env):
        if key.startswith(('OUTREACH_', 'USER_RADAR_')):
            del env[key]
    env.update(OUTREACH_DATA=str(base/'OutreachPilot'),
               USER_RADAR_CUSTOMER_DB=str(base/'UserRadar'/'customers.sqlite3'),
               USER_RADAR_EXTENSION_CONFIG=str(base/'UserRadar'/'extension-pairing.json'),
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    return base, env

def available(port):
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1', port)) != 0

def ready(port, path):
    try:
        req=urllib.request.Request('http://127.0.0.1:%s%s' % (port,path))
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=1) as response:
            return response.status==200
    except Exception:
        return False

def command(code):
    # Embedded Python ignores PYTHONPATH: explicitly set the application import path.
    return [sys.executable, '-X', 'utf8', '-c', 'import sys; sys.path.insert(0, '+repr(str(ROOT))+'); '+code]

def singleton():
    if sys.platform != 'win32':return None
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    handle=kernel.CreateMutexW(None,False,'Local\\UserRadarCustomerRunning')
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error()==183:
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        kernel.CloseHandle(handle)
        raise RuntimeError('User Radar is already running. Open http://127.0.0.1:18800')
    return kernel,handle

def main():
    lock=singleton()  # Keep the mutex alive for the entire supervisor process.
    base,env=environment()
    if not all(available(port) for port in (18800,18830)):
        raise RuntimeError('Port 18800 or 18830 is in use. Close the existing app first; no process was stopped.')
    # Reset only this customer's account pause flags before starting workers.
    pause="from outreach import config,store; store.db(); [store.put('paused_'+a['id'],True) for a in config.load()['accounts']]; store.close()"
    subprocess.run(command(pause),cwd=ROOT,env=env,check=True)
    children=[]
    try:
        for name,args in [('outreach',[str(ROOT/'app.py'),'--no-browser']),('radar',[str(ROOT/'userradar'/'app.py')])]:
            with (base/(name+'.log')).open('ab') as log:
                code='import runpy; sys.path.insert(0, '+repr(str(Path(args[0]).parent))+'); sys.argv='+repr(args)+'; runpy.run_path('+repr(args[0])+',run_name="__main__")'
                children.append(subprocess.Popen(command(code),cwd=ROOT,env=env,stdout=log,stderr=log))
        for _ in range(100):
            if any(p.poll() is not None for p in children):
                raise RuntimeError('Service exited. Logs: '+str(base))
            if ready(18800,'/api/ping') and ready(18830,'/api/health'):break
            time.sleep(.2)
        else:raise RuntimeError('Startup timeout. Logs: '+str(base))
        webbrowser.open('http://127.0.0.1:18800')
        print('Outreach: http://127.0.0.1:18800\nWebsite research: http://127.0.0.1:18830')
        print('All accounts start PAUSED. Read the manual before sending.\nPause in the app before closing this window. Ctrl+C exits.')
        while all(p.poll() is None for p in children):time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in children:
            if p.poll() is None:p.terminate()
        for p in children:
            try:p.wait(timeout=8)
            except subprocess.TimeoutExpired:p.kill();p.wait()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Unable to start:',exc)
        if sys.platform=='win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,str(exc),'User Radar',0x10)
        sys.exit(1)
