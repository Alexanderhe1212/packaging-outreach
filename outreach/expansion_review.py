import os
"""Desktop review of the existing expansion worker state, under a shared lock."""
from pipeline_core import file_lock as fcntl
import hashlib,json,time
from pathlib import Path
from contextlib import contextmanager
from . import store
HOME=Path(os.environ.get("USER_RADAR_EXPANSION_HOME",str(Path.home()/"Library/Application Support/UserRadar/expansion")))
def revision(row):
 return hashlib.sha256(json.dumps(row.get("evidence",{}),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
@contextmanager
def locked():
 HOME.mkdir(parents=True,exist_ok=True)
 with (HOME/"state.lock").open("a") as f:
  fcntl.flock(f,fcntl.LOCK_EX);yield

def load():
 p=HOME/"state.json"
 return json.loads(p.read_text()) if p.exists() else {"rows":[],"status":"paused","calls_today":0}
def save(state):
 p=HOME/"state.json";t=p.with_suffix(".review.tmp");t.write_text(json.dumps(state,ensure_ascii=False,indent=2));t.replace(p)
def overview(_=None):
 with locked():
  state=load();cfg=json.loads((HOME/"config.json").read_text()) if (HOME/"config.json").exists() else {"enabled":False,"daily_search_calls":6}
 rows=[]
 for row in state.get("rows",[]):
  item=dict(row);item["revision"]=revision(row)
  d=row["website"].split("://")[-1].split("/")[0].lower().removeprefix("www.")
  leads=store.q("SELECT id,account,status,error,updated_at FROM leads WHERE lower(domain)=? ORDER BY id DESC LIMIT 3",(d,))
  item["handoffs"]=leads;rows.append(item)
 return dict(rows=rows,status=state.get("status"),error=state.get("error",""),active=state.get("active"),calls_today=state.get("calls_today",0),config=cfg)
def review(data):
 if data.get("decision") not in ("approved","rejected"):raise ValueError("Invalid review decision")
 with locked():
  s=load();row=next((x for x in s["rows"] if x["website"]==data.get("website")),None)
  if not row or revision(row)!=data.get("revision"):raise ValueError("Evidence changed; refresh and review again")
  if data["decision"]=="approved":
   if data.get("grade") not in ("A","B") or data.get("industry_verified") is not True or data.get("compliance_checked") is not True:raise ValueError("Complete industry and compliance review first")
   sources=row.get("evidence",{}).get("candidate",{}).get("sources",[])
   source=data.get("exhibitor_source","")
   if not source or not any(x.get("url")==source for x in sources):raise ValueError("Select an existing exhibitor evidence source")
   row.update(grade=data["grade"],industry_verified=True,compliance_checked=True,exhibitor_source=source,review_revision=revision(row))
  row.update(review=data["decision"],reviewed_at=time.time(),review_note=str(data.get("note","")).strip()[:1500])
  if not row["review_note"]:raise ValueError("Review reason required")
  save(s)
 store.audit("expansion_review","",origin=data.get("_origin"),result=data["decision"])
 return {"ok":True,"message":"Review saved; this action does not send email"}


def configure(data):
 if not isinstance(data.get("enabled"),bool):raise ValueError("Explicit enabled flag required")
 with locked():
  p=HOME/"config.json";cfg=json.loads(p.read_text()) if p.exists() else dict(daily_search_calls=6,max_pending_review=15)
  cfg["enabled"]=data["enabled"]
  tmp=p.with_suffix(".config.tmp");tmp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2));tmp.replace(p)
 store.audit("expansion_configured","",origin=data.get("_origin"),result="enabled" if cfg["enabled"] else "paused")
 return {"ok":True}
