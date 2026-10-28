"""Export tracked runtime sources only; never traverse live data directories."""
import hashlib,html,json,re,shutil,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(sys.argv[1]).resolve()
DEST=OUT/'UserRadar-Windows-Preview-20261028'
if DEST.exists():raise SystemExit('Output exists; choose a new directory')
DEST.mkdir(parents=True)
tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
for name in tracked:
    p=Path(name)
    if not name or p.name.startswith('test') or any(x in ('__pycache__','test-fixtures','research-runs','benchmark10-new') for x in p.parts):continue
    allowed=(name in ('app.py','LICENSE','defaults.json','profiles/packaging.json','outreach/copy_guidance.txt') or
             (p.parts[0] in ('outreach','pipeline_core') and p.suffix in ('.py','.cjs')) or
             (p.parts[0]=='ui' and p.name in ('index.html','radar.html','problems.html','funnel.html','workspace.css')) or
             (p.parts[0]=='userradar' and len(p.parts)==2 and p.suffix in ('.py','.js','.html','.cjs')) or
             (name.startswith('userradar/pipeline_core/') and p.suffix=='.py') or
             (name.startswith('userradar/third_party/') and (p.suffix in ('.py','.txt','.md','.rst') or p.name.startswith(('LICENSE','COPYING','NOTICE'))) and not any(x.startswith('test') for x in p.parts)))
    if not allowed:continue
    src=ROOT/name
    if src.is_symlink() and (not src.resolve().is_relative_to(ROOT) or not src.resolve().is_file()):raise ValueError('Refuse external symlink '+name)
    target=DEST/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
shutil.copytree(DEST/'pipeline_core',DEST/'userradar'/'pipeline_core',dirs_exist_ok=True)
# Personal machine paths are not customer configuration. Optional integrations are unconfigured.
for p in DEST.rglob('*'):
    if not p.is_file():continue
    text=p.read_text(encoding='utf-8')
    text=text.replace('/Users/hugo/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node','node')
    text=text.replace('/Users/hugo/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright','playwright')
    text=text.replace('/Users/hugo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3','python')
    p.write_text(text,encoding='utf-8')
# No named customer project profiles or example account credentials.
for name in ('launcher.py','Start.cmd','Setup.cmd','requirements-windows.txt','使用说明书.md','验证报告.md'):
    source=Path(__file__).parent/name
    (DEST/name).write_bytes(source.read_bytes())
for name in ('Start.cmd','Setup.cmd'):
    p=DEST/name;p.write_bytes(p.read_text().replace('\n','\r\n').encode('ascii'))
# Standalone readable/printable manual, with no remote assets.
def inline(text):
    text=html.escape(text)
    text=re.sub(r'`([^`]+)`',r'<code>\1</code>',text)
    return re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',text)
parts=[]
in_table=False
for line in (DEST/'使用说明书.md').read_text().splitlines():
    if not line.strip():
        if in_table:parts.append('</table>');in_table=False
        continue
    heading=re.match(r'^(#{1,3}) (.*)',line)
    if heading:parts.append('<h%d>%s</h%d>'%(len(heading[1]),html.escape(heading[2]),len(heading[1])))
    elif line.startswith('|'):
        if re.fullmatch(r'[| :\-]+',line):continue
        if not in_table:parts.append('<table>');in_table=True
        parts.append('<tr>'+''.join('<td>'+inline(cell.strip())+'</td>' for cell in line.strip('|').split('|'))+'</tr>')
    else:parts.append('<p>'+inline(line)+'</p>')
(DEST/'使用说明书.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>User Radar 使用说明书</title><style>body{max-width:900px;margin:48px auto;padding:0 24px;font:16px/1.9 system-ui,Microsoft YaHei,sans-serif;color:#193434}h1{border-bottom:4px solid #178075;padding-bottom:20px}h2{margin-top:40px;color:#10675f}table{width:100%;border-collapse:collapse;font-size:14px}td{padding:10px;border:1px solid #d9e4e2}tr:first-child{background:#e8f3f1;font-weight:bold}code{background:#edf2f2;padding:2px 4px;overflow-wrap:anywhere}@media print{body{margin:0}h2{break-after:avoid}}</style><body>'+''.join(parts)+'</body></html>',encoding='utf-8')
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip()
(DEST/'SOURCE.json').write_text(json.dumps({'revision':revision,'edition':'Windows preview; not Windows-validated','source_changes':'Portable launcher and documented path substitutions only'},indent=2))
manifest={str(p.relative_to(DEST)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DEST.rglob('*')) if p.is_file()}
(DEST/'SHA256SUMS.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
zip_path=OUT/(DEST.name+'.zip')
with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(DEST.rglob('*')):
        if p.is_file():z.write(p,str(p.relative_to(OUT)))
print(json.dumps({'folder':str(DEST),'zip':str(zip_path),'files':len(manifest),'bytes':zip_path.stat().st_size},ensure_ascii=False))
