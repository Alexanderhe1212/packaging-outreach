"""Build native artifacts on their target OS, using only repository runtime files."""
import pathlib,subprocess,sys,shutil,zipfile,tarfile,json,hashlib
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=ROOT/'dist';OUT.mkdir(exist_ok=True)
sep=';' if sys.platform=='win32' else ':'
args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--name','UserRadar','--onedir','--collect-all','PySide6','--collect-data','outreach','--collect-submodules','outreach','--collect-submodules','pipeline_core','--collect-submodules','userradar']
for name in ['app.py','defaults.json','profiles','ui','userradar']:
 args+=['--add-data',str(ROOT/name)+sep+name if (ROOT/name).is_dir() else str(ROOT/name)+sep+'.']
args+=['--paths',str(ROOT),'--paths',str(ROOT/'userradar')]
if sys.platform=='darwin':args+=['--windowed','--osx-bundle-identifier','com.packagingoutreach.userradar']
args+=[str(ROOT/'distribution/desktop/launcher.py')]
subprocess.run(args,cwd=ROOT,check=True)
exe=OUT/'UserRadar'/('UserRadar.exe' if sys.platform=='win32' else 'UserRadar')
if sys.platform=='darwin':exe=OUT/'UserRadar.app/Contents/MacOS/UserRadar'
subprocess.run([str(exe),'--smoke-test'],check=True,timeout=90)
name='UserRadar-'+{'win32':'Windows-x64','darwin':'macOS','linux':'Linux-x64'}[sys.platform]
if sys.platform=='darwin':
 subprocess.run(['codesign','--force','--deep','--sign','-',str(OUT/'UserRadar.app')],check=True)
 subprocess.run(['codesign','--verify','--deep','--strict',str(OUT/'UserRadar.app')],check=True)
 subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(OUT/'UserRadar.app'),str(OUT/(name+'.zip'))],check=True)
elif sys.platform=='win32':
 shutil.make_archive(str(OUT/name),'zip',OUT/'UserRadar')
else:
 with tarfile.open(OUT/(name+'.tar.gz'),'w:gz') as archive:archive.add(OUT/'UserRadar',arcname='UserRadar')
artifacts=[p for p in OUT.iterdir() if p.is_file() and p.suffix in ('.zip','.gz')]
(OUT/'SHA256SUMS.txt').write_text('\n'.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name for p in artifacts)+'\n')
print(json.dumps({'platform':sys.platform,'smoke_test':'passed','artifacts':[p.name for p in artifacts]}))
