"""Bundled desktop supervisor. Opening always pauses the local accounts; never sends."""
import json,os,signal,tempfile,pathlib,runpy,socket,subprocess,sys,time,urllib.request
ROOT=pathlib.Path(getattr(sys,'_MEIPASS',pathlib.Path(__file__).resolve().parents[2]))
def environment():
    if sys.platform=='win32':base=pathlib.Path(os.environ.get('LOCALAPPDATA',str(pathlib.Path.home())))/'UserRadar'
    elif sys.platform=='darwin':base=pathlib.Path.home()/'Library/Application Support/UserRadarDesktop'
    else:base=pathlib.Path(os.environ.get('XDG_DATA_HOME',str(pathlib.Path.home()/'.local/share')))/'user-radar'
    base.mkdir(parents=True,exist_ok=True)
    env={k:v for k,v in os.environ.items() if not k.startswith(('OUTREACH_','USER_RADAR_'))}
    env.update(OUTREACH_DATA=str(base/'outreach'),USER_RADAR_CUSTOMER_DB=str(base/'customers.sqlite3'),USER_RADAR_EXTENSION_CONFIG=str(base/'extension-pairing.json'),USER_RADAR_EXPANSION_HOME=str(base/'expansion'),PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    return base,env

def service(name):
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'userradar'))
    target=ROOT/('app.py' if name=='outreach' else 'userradar/exhibitor_expansion.py' if name=='expansion' else 'userradar/app.py')
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
        env.update(OUTREACH_DATA=str(base/'outreach'),USER_RADAR_CUSTOMER_DB=str(base/'customers.sqlite3'),USER_RADAR_EXPANSION_HOME=str(base/'expansion'))
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
    expansion=pathlib.Path(env['USER_RADAR_EXPANSION_HOME']);expansion.mkdir(parents=True,exist_ok=True)
    for filename,value in [('config.json',dict(enabled=False,daily_search_calls=6,max_pending_review=15)),('state.json',dict(rows=[],calls_today=0,status='paused'))]:
        if not (expansion/filename).exists():(expansion/filename).write_text(json.dumps(value),encoding='utf-8')
    children=[]
    if '--serve-only' in sys.argv:
        signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        for name in ('outreach','radar','expansion'):
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
            if sys.platform=='darwin':
                print(json.dumps({'ok':True,'platform':sys.platform,'accounts_paused':True,'services':2,'smtp_calls':0}));return
            os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS','--disable-gpu --no-sandbox')
            from PySide6.QtWidgets import QApplication
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtCore import QUrl,QTimer
            app=QApplication(sys.argv);view=QWebEngineView();view.resize(1100,800);result=[]
            def loaded(ok):
                if not ok:result.append(False);app.quit();return
                view.page().runJavaScript("document.querySelector('h1')?.textContent",lambda text:(result.append(text=='首次接入指导'),app.quit()))
            view.loadFinished.connect(loaded);QTimer.singleShot(20000,app.quit)
            view.setUrl(QUrl('http://127.0.0.1:%d/setup'%ports[0]));view.show();app.exec()
            assert result==[True],'Desktop setup page failed to render'
            print(json.dumps({'ok':True,'platform':sys.platform,'accounts_paused':True,'services':2,'setup_page_rendered':True,'smtp_calls':0}));return
        if '--serve-only' in sys.argv:
            print('USER_RADAR_READY',flush=True)
            while all(p.poll() is None for p in children):time.sleep(1)
            return
        from PySide6.QtWidgets import QApplication,QMainWindow,QToolBar
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        app=QApplication(sys.argv);window=QMainWindow();window.setWindowTitle('User Radar');window.resize(1250,850)
        view=QWebEngineView();view.page().newWindowRequested.connect(lambda req:QDesktopServices.openUrl(req.requestedUrl()) if req.requestedUrl().scheme() in ('http','https') else None);window.setCentralWidget(view);bar=QToolBar();window.addToolBar(bar)
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
