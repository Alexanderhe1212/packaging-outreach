"""Prepare an offline Windows x64 payload; compile installer separately with NSIS."""
import ast,hashlib,json,re,shutil,subprocess,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
BUILD=Path(sys.argv[1]).resolve()
PAYLOAD=BUILD/'payload'
if PAYLOAD.exists():raise SystemExit('payload exists; use a clean staging folder')
subprocess.run([sys.executable,str(HERE/'build_package.py'),str(BUILD/'source-export')],check=True)
source=BUILD/'source-export'/'UserRadar-Windows-Preview-20261028'
app=PAYLOAD/'app';app.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(source,app)
# No end-user package manager or outdated source-preview setup instructions.
for name in ('Setup.cmd','Start.cmd','requirements-windows.txt','SHA256SUMS.json','SOURCE.json'):(app/name).unlink()
manual=(HERE/'安装版使用说明书.md').read_text()
(app/'使用说明书.md').write_text(manual,encoding='utf-8')
# Reuse the exact local renderer used for the preview manual.
renderer=(HERE/'build_package.py').read_text().split('# Standalone readable/printable manual, with no remote assets.')[1].split('revision=subprocess.check_output')[0]
import html
exec(renderer,{'DEST':app,'html':html,'re':re})
report='''# 安装包验证边界\n\nWindows x64 自带运行环境安装包。无需安装 Python 或依赖。\n\n构建验证、运行环境校验和模拟测试见交付目录中的 build-report.json。尚未进行真实 Windows 实机、SMTP/IMAP 或模型服务验收。安装包未商业签名。\n\n应用启动时账号暂停，不启动发送。卸载保留独立客户数据目录。仅导出运行源码、通用模板和依赖，未读取真实运行数据。\n'''
(app/'验证报告.md').write_text(report,encoding='utf-8')
# Public PDF reads must use our embedded interpreter, not a system Python.
p=app/'userradar/public_sources.py';s=p.read_text().replace("BUNDLED_PYTHON='python'","import sys\nBUNDLED_PYTHON=sys.executable");p.write_text(s,encoding='utf-8')
# The browser extension adapter must read this customer's pairing location.
p=app/'outreach/radar.py';s=p.read_text().replace('import json\n','import json\nimport os\n',1).replace("pairing=Path.home()/'Library/Application Support/UserRadar/extension-pairing.json'","pairing=Path(os.environ.get('USER_RADAR_EXTENSION_CONFIG',str(Path.home()/'Library/Application Support/UserRadar/extension-pairing.json')))")
p.write_text(s,encoding='utf-8')
# Runtime-specific installers must not be overwritten by the source-only updater.
p=app/'outreach/updater.py';s=p.read_text().replace('def check():', 'def check():\n    return {"current": VERSION, "latest": VERSION, "update": False, "mode": "installer", "error": "Windows 安装版请使用新版 EXE 安装包更新"}\n')
s=s.replace('def apply():', 'def apply():\n    raise RuntimeError("Windows 安装版请使用新版 EXE 安装包更新；业务数据保留")\n')
p.write_text(s,encoding='utf-8')
runtime=PAYLOAD/'runtime';runtime.mkdir()
archive=BUILD/'downloads/python-3.14.10-embed-amd64.zip'
expected='90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159'
assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected,'Python official hash mismatch'
with zipfile.ZipFile(archive) as z:
 for name in z.namelist():
  if not (runtime/name).resolve().is_relative_to(runtime):raise ValueError('Unsafe runtime member')
 z.extractall(runtime)
(runtime/'python314._pth').write_text('python314.zip\n.\nLib/site-packages\nimport site\n',encoding='ascii')
subprocess.run([sys.executable,'-m','pip','install','--no-index','--find-links',str(BUILD/'wheels'),'--only-binary=:all:','--platform','win_amd64','--python-version','314','--implementation','cp','--abi','cp314','--no-compile','--target',str(runtime/'Lib/site-packages'),'-r',str(HERE/'requirements-windows.txt')],check=True)
# Pip may emit launcher scripts that are not used. Keep libraries and license metadata.
for name in ('bin','Scripts'):
 p=runtime/'Lib/site-packages'/name
 if p.exists():shutil.rmtree(p)
for p in app.rglob('*.py'):ast.parse(p.read_text())
for p in app.rglob('*'):
 if p.is_file():
  if p.name in ('settings.json','secrets.json','.env') or p.suffix in ('.db','.sqlite3','.eml','.log'):raise ValueError('Private artifact '+str(p))
  text=p.read_text(errors='ignore')
  if '/Users/hugo/' in text or re.search(r'sk-[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16}|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY',text):raise ValueError('Private marker '+str(p))
manifest={str(p.relative_to(PAYLOAD)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(PAYLOAD.rglob('*')) if p.is_file()}
(app/'payload-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(BUILD/'dependency-hashes.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((BUILD/'wheels').glob('*.whl'))},indent=2))
shutil.copyfile(HERE/'installer.nsi',BUILD/'installer.nsi')
print(json.dumps({'payload_files':len(manifest),'runtime':'CPython 3.14.10 Windows x64','python_sha256_verified':True,'bytes':sum(p.stat().st_size for p in PAYLOAD.rglob('*') if p.is_file())}))
