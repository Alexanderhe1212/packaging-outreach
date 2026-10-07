"""Generic structure vocabulary; user's PDF images stay in a private manifest."""
import hashlib,json
from pathlib import Path
RIGID_BOXES={
 'lid-base':'Separate lift-off lid and base',
 'drawer':'Sliding tray partly retained on the sleeve axis',
 'hinged':'Hinged rigid box with a physical closure',
 'collapsible':'Foldable hinged rigid box with plausible corner assembly',
 'window':'Hinged box with an actual window panel',
 'double-door':'Two hinged doors around one central product support',
 'shoulder':'Lid and base around a visible shoulder',
 'shaped':'Product-appropriate shaped rigid box with a specified opening'}
FOLDING_CARTONS={
 'folding-ste':'Straight-tuck-end folding paperboard carton',
 'folding-rte':'Reverse-tuck-end folding paperboard carton',
 'folding-auto-lock':'Auto-lock-bottom folding paperboard carton with tuck top',
 'folding-sleeve':'Folding-paperboard sleeve with a lightweight sliding carton tray'}
BOXES=dict(RIGID_BOXES,**FOLDING_CARTONS)
INSERTS=['folded-card','corrugated','pearl-foam','sponge','black-eva','white-eva','clear-thermoform','flocked-thermoform']
FOLDING_CARTON_SUPPORTS=['folded-card','corrugated']
ACCESSORIES=['grosgrain-ribbon','satin-ribbon','two-tone-ribbon','printed-ribbon','handle-cord','wrapping-tissue','decorative-filler']

def context(store,profile=None):
 with store.db() as c:rows=c.execute("SELECT profile_id,plan FROM plan_summaries WHERE stage IN ('draft','send','done') ORDER BY updated DESC LIMIT 60").fetchall()
 recent=[json.loads(x['plan'] or '{}') for x in rows if not profile or x['profile_id']==profile['id']][:12]
 return {'structures':profile['structures'] if profile else BOXES,'supports':profile['supports'] if profile else INSERTS,'accessories':profile['accessories'] if profile else ACCESSORIES,'recent_selections':[{k:r.get(k,{}).get('structure',r.get(k,{}).get('box')) for k in ['a','b']} for r in recent]}

def selected_images(plan,manifest_path):
 if not manifest_path:return []
 manifest_path=Path(manifest_path);root=manifest_path.parent.resolve();manifest=json.loads(manifest_path.read_text());wanted=set()
 for option in [plan['a'],plan['b']]:wanted.update([option.get('structure',option.get('box')),option.get('support',option.get('insert'))]+option.get('accessories',[]))
 result=[];seen=set()
 for entry in manifest.get('references',[]):
  if not wanted.intersection(entry['ids']):continue
  p=(root/entry['file']).resolve()
  if not p.is_relative_to(root) or (root/entry['file']).is_symlink():raise ValueError('Reference must stay inside private material directory')
  raw=p.read_bytes()
  if len(raw)>8*1024*1024 or hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Material reference changed')
  if p not in seen:result.append((raw,'image/png'));seen.add(p)
 return result
