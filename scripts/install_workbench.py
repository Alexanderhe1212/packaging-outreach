"""Install the macOS desktop workbench without copying private runtime data."""
import argparse, os, plistlib, shutil, socket, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def check():
    for name in ('app.py','outreach/server.py','ui/problems.html','radar/app.py','desktop/Main.swift','desktop/controller.py'):
        if not (ROOT/name).is_file():raise RuntimeError('Missing source: '+name)

def install():
    check()
    if sys.platform != 'darwin':raise RuntimeError('Desktop workbench requires macOS; the standalone mail backend remains cross-platform.')
    for port in (18800,18830):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',port)) == 0:
                raise RuntimeError('Close the running backend before installing an update (port %s). Customer data will be preserved.' % port)
    support=Path.home()/'Library/Application Support'
    app=support/'OutreachPilot/app';radar=support/'UserRadar/automatic-app';desktop=support/'UserRadar/desktop'
    for dst in (app,radar,desktop):dst.mkdir(parents=True,exist_ok=True)
    for folder in ('outreach','ui','profiles'):shutil.copytree(ROOT/folder,app/folder,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('app.py','defaults.json','LICENSE'):shutil.copy2(ROOT/name,app/name)
    shutil.copytree(ROOT/'radar',radar,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','.venv','node_modules','research-runs','config.js'))
    for name in ('Main.swift','controller.py','dashboard.html'):shutil.copy2(ROOT/'desktop'/name,desktop/name)
    subprocess.run([sys.executable,'-m','venv',str(radar/'.venv')],check=True)
    python=str(radar/'.venv/bin/python')
    subprocess.run([python,'-m','pip','install','-r',str(radar/'requirements.txt')],check=True)
    subprocess.run([python,'-c','from prepare_chrome_extension import prepare; prepare()'],cwd=radar,check=True)
    bundle=Path.home()/'Desktop/User Radar 工作台.app';contents=bundle/'Contents';(contents/'MacOS').mkdir(parents=True,exist_ok=True)
    subprocess.run(['xcrun','swiftc',str(desktop/'Main.swift'),'-framework','Cocoa','-framework','WebKit','-o',str(contents/'MacOS/UserRadarDesktop')],check=True)
    info=dict(CFBundleName='User Radar 工作台',CFBundleDisplayName='User Radar 工作台',CFBundleIdentifier='com.userradar.desktop.workspace',CFBundleExecutable='UserRadarDesktop',CFBundlePackageType='APPL',CFBundleShortVersionString='0.2.0',CFBundleVersion='2',NSHighResolutionCapable=True,NSAppTransportSecurity={'NSAllowsLocalNetworking':True,'NSAllowsArbitraryLoadsInWebContent':True})
    (contents/'Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(['codesign','--force','--deep','--sign','-',str(bundle)],check=True)
    logs=Path.home()/'Library/Logs/UserRadar';logs.mkdir(parents=True,exist_ok=True)
    label='com.userradar.autoprospect';agents=Path.home()/'Library/LaunchAgents';agents.mkdir(parents=True,exist_ok=True)
    plist=agents/(label+'.plist')
    plist.write_bytes(plistlib.dumps(dict(Label=label,ProgramArguments=[python,str(radar/'auto_prospect.py')],WorkingDirectory=str(radar),RunAtLoad=True,KeepAlive=True,ThrottleInterval=30,StandardOutPath=str(logs/'automatic.log'),StandardErrorPath=str(logs/'automatic-error.log'),EnvironmentVariables={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'PYTHONUNBUFFERED':'1'})))
    # The worker waits for explicit account start; installation never starts sending.
    subprocess.run(['launchctl','bootout','gui/%s/%s'%(os.getuid(),label)],capture_output=True)
    subprocess.run(['launchctl','bootstrap','gui/%s'%os.getuid(),str(plist)],check=True)
    print('Installed:',bundle)
    print('Configure MTT/GUKA accounts and AI in the app, then explicitly start. Existing customer databases/settings were not copied or deleted.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    if args.check:check();print('Source layout OK; no installation or sending performed.')
    else:install()
