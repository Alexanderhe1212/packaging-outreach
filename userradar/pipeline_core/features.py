"""Reloadable rollout switches, separate from accounts and credentials."""
import json,os
from pathlib import Path
DEFAULTS=dict(evidence_pack=True,candidate_pool=True,unified_retry=True,reply_classification=True,
              send_guard=False,auto_followup=False,account_routing=False,second_contact=False)
def data_root():return Path(os.environ.get('OUTREACH_DATA',str(Path.home()/'Library/Application Support/OutreachPilot')))
def settings():
 try:
  value=json.loads((data_root()/'pipeline-features.json').read_text())
  return value if isinstance(value,dict) else {}
 except (OSError,ValueError):return {}
def enabled(name):
 value=settings().get(name,DEFAULTS.get(name,False))
 return value is True
def option(name,default):return settings().get(name,default)

def update(values):
    if not isinstance(values,dict) or any(k not in DEFAULTS or not isinstance(v,bool) for k,v in values.items()):raise ValueError('Only named boolean pipeline switches are accepted')
    current=settings();current.update(values)
    folder=data_root();folder.mkdir(parents=True,exist_ok=True)
    target=folder/'pipeline-features.json'
    if target.is_symlink():raise ValueError('feature file must not be a symlink')
    import tempfile
    fd,name=tempfile.mkstemp(prefix='pipeline-features-',dir=folder)
    try:
        with os.fdopen(fd,'w') as stream:json.dump(current,stream,ensure_ascii=False,indent=2)
        os.replace(name,target)
    finally:
        if os.path.exists(name):os.unlink(name)
    return {key:enabled(key) for key in DEFAULTS}
