"""Update helpers in an existing User Radar installation; no data or credentials copied."""
import argparse
import shutil
from pathlib import Path

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--radar-dir',type=Path,required=True)
a=p.parse_args();target=a.radar_dir.resolve()
if not all((target/name).is_file() for name in ('app.py','customer_store.py','exhibition_handoff.py')):
    raise SystemExit('Expected an existing User Radar installation; nothing changed.')
for source,name in [(root/'radar_automation/auto_prospect.py','auto_prospect.py'),(root/'radar_automation/recheck_queue.py','recheck_queue.py'),(root/'outreach/prospect_filter.py','prospect_filter.py')]:
    temporary=target/(name+'.new');shutil.copy2(source,temporary);temporary.replace(target/name)
print('Helpers updated. Gracefully restart the existing automatic worker to load them.')
