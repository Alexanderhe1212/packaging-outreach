"""Domain-email leads only; no names, roles, phones or qualification inferred."""
import html
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

WORKER=Path(__file__).resolve().parent/'third_party/theHarvester/email_worker.py'

def email_hints(raw,source,*,diagnostics=None,target_domain=None):
    info=diagnostics if diagnostics is not None else {}
    info.update(engine='theHarvester 4.8.2 Parser',status='not_needed',network_requests=0)
    text=html.unescape(raw[:250_000])
    if '@' not in text:return []
    domain=(target_domain or urlsplit(source).hostname or '').lower().removeprefix('www.')
    if not domain or not WORKER.exists():
        info['status']='unavailable';return []
    try:
        result=subprocess.run([sys.executable,str(WORKER)],input=json.dumps({'domain':domain,'text':text},ensure_ascii=False),text=True,capture_output=True,timeout=3,check=True)
        values=json.loads(result.stdout)['emails']
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        info.update(status='incomplete',error=type(error).__name__);return []
    info.update(status='parsed',email_leads=len(values))
    return [dict(email=email,source=source,engine='theHarvester 4.8.2 Parser',qualified=False,status='公开页面邮箱线索；姓名、职位及本人归属尚未核实') for email in values]
