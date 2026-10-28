"""Save public business access first; reuse the existing bounded identity enrichment jobs."""
import json,time
from pathlib import Path
import team_enrichment,customer_store
from name_email_lookup import qualify_report
from extension_api import safe_contact
from recheck_queue import write

def schedule(path,website,report,company):
    path=Path(path)
    rows=json.loads(path.read_text()) if path.exists() else []
    if any(r['website']==website for r in rows):return
    if sum(r['status'] in ('starting','researching') for r in rows)>=3:
        rows.append(dict(website=website,company=company,status='pending',created_at=time.time(),official_report=report));write(path,rows);return
    row=dict(website=website,company=company,status='starting',created_at=time.time());rows.append(row);write(path,rows)
    try:
        row['job']=team_enrichment.start_team(website,official_report=report,core_only=True,max_seconds=180)
        row['status']='researching'
    except Exception as exc:row.update(status='review',reason_code='POST_UNKNOWN',error=str(exc)[:250])
    write(path,rows)

def poll(path):
    path=Path(path)
    if not path.exists():return
    rows=json.loads(path.read_text())
    for row in rows:
        if row['status']=='starting':row.update(status='review',reason_code='POST_UNKNOWN')
        if row['status']!='researching':continue
        try:job=team_enrichment.get_team(row['job']['id'])
        except ValueError:row.update(status='review',reason_code='JOB_EXPIRED');continue
        if job['status'] not in team_enrichment.TERMINAL:continue
        report=qualify_report(job.get('report') or {})
        contacts=[safe_contact(p,row['website'],report,name_email_only=True) for p in report.get('qualified_people',[])]
        from auto_prospect import contact_priority
        contacts=sorted((p for p in contacts if p and p.get('name') and p.get('email')),key=contact_priority)
        if contacts:
            contact=contacts[0];contact['company']=row['company']
            receipt=customer_store.save(contact,upgrade=True)
            row.update(status='saved',contact_id=receipt['customer']['id'])
        else:row.update(status='review',reason_code='NO_NAMED_BUYER')
    # Persist a start reservation before issuing a job, so uncertain starts are never repeated.
    slots=3-sum(r['status'] in ('starting','researching') for r in rows)
    for row in rows:
        if slots<=0:break
        if row['status']!='pending':continue
        row['status']='starting';write(path,rows);slots-=1
        try:
            row['job']=team_enrichment.start_team(row['website'],official_report=row.get('official_report',{}),core_only=True,max_seconds=180)
            row['status']='researching';row.pop('official_report',None)
        except Exception as exc:row.update(status='review',reason_code='POST_UNKNOWN',error=str(exc)[:250])
    write(path,rows)
