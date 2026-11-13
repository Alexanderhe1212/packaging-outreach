"""Bundled desktop supervisor. Opening always pauses the local accounts; never sends."""
import json,os,tempfile,pathlib,runpy,socket,subprocess,sys,time,urllib.request
ROOT=pathlib.Path(getattr(sys,'_MEIPASS',pathlib.Path(__file__).resolve().parents[2]))
def environment():
    if sys.platform=='win32':base=pathlib.Path(os.environ.get('LOCALAPPDATA',str(pathlib.Path.home())))/'UserRadar'
    elif sys.platform=='darwin':base=pathlib.Path.home()/'Library/Application Support/UserRadarDesktop'
    else:base=pathlib.Path(os.environ.get('XDG_DATA_HOME',str(pathlib.Path.home()/'.local/share')))/'user-radar'
    base.mkdir(parents=True,exist_ok=True)
    env={k:v for k,v in os.environ.items() if not k.startswith(('OUTREACH_','USER_RADAR_'))}
    env.update(OUTREACH_DATA=str(base/'outreach'),USER_RADAR_CUSTOMER_DB=str(base/'customers.sqlite3'),USER_RADAR_EXTENSION_CONFIG=str(base/'extension-pairing.json'),PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    return base,env

def service(name):
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'userradar'))
    target=ROOT/('app.py' if name=='outreach' else 'userradar/app.py')
    sys.argv=[str(target),'--no-browser'] if name=='outreach' else [str(target)]
    runpy.run_path(str(target),run_name='__main__')

def request(port,path):
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:%d%s'%(port,path),timeout=1) as r:return json.load(r)

def main():
    if '--service' in sys.argv:return service(sys.argv[sys.argv.index('--service')+1])
    base,env=environment()
    ports=[18800,18830]
    if '--smoke-test' in sys.argv:
        base=pathlib.Path(tempfile.mkdtemp(prefix='userradar-smoke-'))
        env.update(OUTREACH_DATA=str(base/'outreach'),USER_RADAR_CUSTOMER_DB=str(base/'customers.sqlite3'))
        for i in range(2):
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));ports[i]=sock.getsockname()[1]
        env.update(OUTREACH_PORT=str(ports[0]),USER_RADAR_PORT=str(ports[1]))
    os.environ.update(env);sys.path.insert(0,str(ROOT))
    for port in ports:
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('Another local service is using port %s; close that application first.'%port)
    from outreach import config,store
    store.db()
    for a in config.load()['accounts']:store.put('paused_'+a['id'],True)
    store.close()
    children=[]
    try:
        for name in ('outreach','radar'):
            cmd=[sys.executable,'--service',name] if getattr(sys,'frozen',False) else [sys.executable,str(pathlib.Path(__file__).resolve()),'--service',name]
            with (base/(name+'.log')).open('ab') as log:children.append(subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=log,stderr=log))
        for _ in range(150):
            if any(p.poll() is not None for p in children):raise RuntimeError('Service exited. Logs: '+str(base))
            try:
                if request(ports[0],'/api/ping').get('ok') and request(ports[1],'/api/health').get('ok'):break
            except Exception:pass
            time.sleep(.2)
        else:raise RuntimeError('Local startup timed out. Logs: '+str(base))
        if '--smoke-test' in sys.argv:
            state=request(ports[0],'/api/state')
            assert all(a['paused'] for a in state['accounts'])
            print(json.dumps({'ok':True,'platform':sys.platform,'accounts_paused':True,'services':2,'smtp_calls':0}));return
        from PySide6.QtWidgets import QApplication,QMainWindow,QToolBar
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtCore import QUrl
        app=QApplication(sys.argv);window=QMainWindow();window.setWindowTitle('User Radar');window.resize(1250,850)
        view=QWebEngineView();window.setCentralWidget(view);bar=QToolBar();window.addToolBar(bar)
        for title,path in [('接入 / Setup','/setup'),('邮件 / Mail','/'),('展会审核 / Exhibitors','/expansion'),('客户 / Contacts','/radar'),('设置 / Settings','/?view=settings')]:
            action=bar.addAction(title);action.triggered.connect(lambda checked=False,p=path:view.setUrl(QUrl('http://127.0.0.1:18800'+p)))
        view.setUrl(QUrl('http://127.0.0.1:18800/setup'));window.show();app.exec()
    finally:
        for p in children:
            if p.poll() is None:p.terminate()
        for p in children:
            try:p.wait(timeout=8)
            except subprocess.TimeoutExpired:p.kill();p.wait()
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('User Radar could not start:',e,file=sys.stderr);sys.exit(1)
