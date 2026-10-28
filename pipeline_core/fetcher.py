import urllib.error
"""Shared evidence-first read adapter. Existing guarded transports remain fallback."""
from . import evidence,features

def publish(url,body,final=None):
 if not features.enabled('evidence_pack') or url.endswith('/robots.txt'):return
 try:
  if len(body)>2000000:return
  evidence.put(url,'page',{'body':body,'final':final or url},final or url,body[:8000],key=url)
 except Exception:pass

def read(url,transport,refresh=False,alternate=None):
 if features.enabled('evidence_pack') and not url.endswith('/robots.txt'):
  try:
   row=evidence.get(url,'page',key=url)
   if not refresh and row and evidence.company_key(row['payload']['final'])==evidence.company_key(url):return row['payload']['body'],row['payload']['final']
  except Exception:pass
 try:
  blocked=evidence.get(url,'blocked') if features.enabled('evidence_pack') else None
 except Exception:blocked=None
 if blocked:raise urllib.error.HTTPError(url,403,'BLOCKED: manual review required',{},None)
 try:body,final=transport(url)
 except urllib.error.HTTPError as error:
  if error.code!=403 or not features.enabled('evidence_pack'):raise
  try:body,final=(alternate or render)(url)
  except Exception:
   try:evidence.put(url,'blocked',{'reason_code':'BLOCKED'},url,'403 after one ordinary render fallback')
   except Exception:pass
   raise error
 publish(url,body,final);return body,final


def render(url):
 """Existing ordinary read-only browser; no authentication/challenge bypass."""
 import socket,ipaddress,subprocess,json,shutil,os
 from pathlib import Path
 from urllib.parse import urlsplit
 p=urlsplit(url)
 if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.port not in (None,80,443):raise ValueError('unsafe browser URL')
 addresses=socket.getaddrinfo(p.hostname,p.port or 443,type=socket.SOCK_STREAM)
 if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError('nonpublic browser target')
 node=shutil.which('node') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
 result=subprocess.run([node,str(Path(__file__).with_name('browser_fetch.cjs'))],input=json.dumps({'url':url,'timeout_ms':48000}),text=True,capture_output=True,timeout=55,check=True)
 value=json.loads(result.stdout)
 if value.get('status')!=200:raise urllib.error.HTTPError(url,value.get('status',403),'render failed',{'Retry-After':value.get('retry_after','')},None)
 if evidence.company_key(value['url'])!=evidence.company_key(url):raise ValueError('render changed company')
 return value['html'],value['url']
