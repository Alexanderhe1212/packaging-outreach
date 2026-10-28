"""Bounded company batches; all work uses the shared company scheduler."""
import threading
import copy
import re
import time
import uuid
from urllib.parse import urlsplit,urlunsplit
import ai_discovery as discovery

BATCHES={}
LOCK=threading.RLock()


def normalize_websites(websites):
    if not isinstance(websites,list) or not 1<=len(websites)<=10:
        raise ValueError('每批请输入 1–10 家公司官网')
    result=[];seen=set()
    for raw in websites:
        if not isinstance(raw,str) or not raw.strip() or len(raw)>2000:raise ValueError('官网地址无效')
        value=raw.strip();value=value if '://' in value else 'https://'+value
        parsed=urlsplit(value)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):raise ValueError('官网地址无效')
        try:parsed.port
        except ValueError:raise ValueError('官网地址无效')
        hostname=parsed.hostname.lower().removeprefix('www.')
        if hostname not in seen:
            seen.add(hostname);result.append(urlunsplit((parsed.scheme,parsed.netloc,parsed.path or '/',parsed.query,'')))
    return result


def start_batch(websites, mode="company"):
    if mode not in ("company", "team", "name_email", "email"):
        raise ValueError("批量查询模式无效")
    values=normalize_websites(websites)
    with LOCK,discovery.LOCK:
        if sum(j['status'] not in discovery.TERMINAL for j in discovery.JOBS.values())+len(values)>30:raise ValueError('等待查询过多，请稍后再试')
        identifier=uuid.uuid4().hex
        for key in list(BATCHES):
            if len(BATCHES)<20:break
            if get_batch(key)['status'] in discovery.TERMINAL:
                old=BATCHES.pop(key)
                for item in old['items']:
                    if item['id'] in discovery.JOBS:discovery.JOBS[item['id']]['retained']=False
        batch={'id':identifier,'items':[],'stopped':False,'mode':mode}
        BATCHES[identifier]=batch
        for website in values:
            if mode in ('team','name_email','email'):
                child_id = uuid.uuid4().hex
                discovery.JOBS[child_id] = dict(id=child_id, idea=TEAM_IDEA,
                    target_website=website, website_first=False, retained=True,
                    queued_at=time.time(), status='queued', progress='等待官网与关键人补查（最多同时 3 家）',
                    results=[], errors=[], notes='', cancel=threading.Event(), mode=mode)
                if mode in ('name_email','email'):
                    from name_email_lookup import run
                    discovery.WORKERS.submit(run,child_id)
                else:discovery.WORKERS.submit(_run_team_company, child_id)
                child = {'id': child_id}
            else:
                child=discovery.start_job('查找官网公司的关键决策人；保留已核实的所有联系人。优先补齐一人的姓名、职位、具名工作邮箱、本人业务手机和本人 WhatsApp；不猜测，不用共享联系方式。',website,website_first=True,retained=True)
            batch['items'].append({'id':child['id'],'website':website})
    return {'id':identifier}


def get_batch(identifier):
    with LOCK:
        batch=BATCHES.get(identifier)
        if not batch:raise ValueError('批量查询记录不存在')
        items=[]
        for item in batch['items']:
            try:job=discovery.get_job(item['id'])
            except ValueError:
                # Completed snapshots outlive the bounded discovery history.
                job=item.get('terminal')
                if not job:raise
            if job['status'] in discovery.TERMINAL:item['terminal']=job
            items.append(dict(job,website=item['website']))
        done=sum(i['status'] in discovery.TERMINAL for i in items)
        terminal=done==len(items)
        status=('cancelled' if batch['stopped'] else 'done') if terminal else ('stopping' if batch['stopped'] else 'running')
        return {'id':identifier,'mode':batch.get('mode','company'),'status':status,'progress':f'已完成 {done}/{len(items)} 家；最多同时查询 3 家','items':items,'results':[r for i in items for r in i['results']],'errors':[e for i in items for e in i['errors']]}


def stop_batch(identifier):
    with LOCK:
        batch=BATCHES.get(identifier)
        if not batch:raise ValueError('批量查询记录不存在')
        batch['stopped']=True
        for item in batch['items']:
            if item.get('terminal'):continue
            try:discovery.stop_job(item['id'])
            except ValueError:pass
    return get_batch(identifier)


TEAM_IDEA = ('查找指定官网公司的关键决策人，优先采购、采购供应链、包装、创始人和相关业务负责人。'
    '姓名、职位、原文明确归属此人的工作邮箱必须齐全；本人手机、本人 WhatsApp 缺项留空。'
    '禁止推算邮箱或 WhatsApp，禁止把公司公共邮箱、客服、前台和共享号码当作个人渠道。')


def key_role_rank(person):
    """Prefer purchasing authority without claiming every executive is a buyer."""
    title = person.get('title', '')
    # Exclude only explicit historical markers, never infer death from age or
    # a founder biography. Keep the observation visible for review.
    if (person.get('historical') or person.get('review_required') or
        re.search(r'\b(?:former|retired|deceased|late|in memoriam)\b|已故|前任|退休', title, re.I)):
        return 9
    if re.search(r'procurement|purchas|sourcing|supply[ -]?chain|采购|供应链', title, re.I):
        return 0
    if re.search(r'investor relations|public relations|press|media relations|customer service|customer support|communications|投资者|公关|客服|新闻', title, re.I):
        return 9
    senior = bool(re.search(r'director|manager|head|chief|vp|vice president|lead|负责人|经理|总监|主管', title, re.I))
    if re.search(r'packaging|包装', title, re.I) and senior:
        return 0
    if re.search(r'engineer|technical|scientist|research|manufactur|production|工程|技术|研发|打样', title, re.I):
        return 9
    if re.search(r'\b(?:ceo|chief executive|owner|president|managing director)\b|老板|总经理|董事长', title, re.I):
        return 1
    if re.search(r'\b(?:founder|co-founder)\b|创始', title, re.I):
        return 3
    if (re.search(r'\b(?:cfo|chief financial officer)\b|director|head of|säljchef|key account manager chef|总监|董事', title, re.I) or
        (senior and re.search(r'business|marketing|sales|export|commercial|operations|销售|业务|市场',title,re.I))):
        return 2
    return 9


def _run_team_company(identifier):
    """Use the existing company scheduler and personal verifier, never queue workers recursively."""
    from app import research, is_role
    from contact_quality import qualify
    from person_identity import plausible_person_name
    import team_enrichment as team
    job = discovery.JOBS[identifier]
    child_id = None
    def update(**changes):
        with discovery.LOCK:
            job.update(changes)
    def channel_safe(report, excluded):
        safe = copy.deepcopy(report)
        safe['people'] = [team.remove_company_channels(p, excluded) for p in safe.get('people', [])]
        for person in safe['people']:
            addresses = [v.strip() for v in person.get('email','').split(';') if v.strip()]
            from enrichment import shared_mailbox
            allowed = [v for v in addresses if v.casefold() not in excluded['emails'] and not shared_mailbox(v,team.domain(safe.get('website','')),safe.get('website',''))]
            if len(allowed) != len(addresses):
                person['email'] = '; '.join(allowed)
                if not allowed:person.setdefault('evidence_by_field',{}).pop('email',None)
        qualify(safe, is_role)
        for person in safe['people']:
            person['key_decision_role'] = key_role_rank(person) < 9
            if not person['key_decision_role']:
                person['qualified'] = False
                person['complete'] = False
                person['key_role_note'] = '保留公开身份及字段，本职位未计作本轮关键决策人'
        safe['qualified_people'] = [p for p in safe['people'] if p.get('qualified')]
        safe['complete_people'] = [p for p in safe['people'] if p.get('complete')]
        return safe
    def public_fallback(reason):
        # Run in place on this company worker; submitting another company job
        # and waiting could deadlock the shared three-worker scheduler.
        with discovery.LOCK:
            job['team_summary'].update(fallback=True, fallback_reason=reason,
                fallback_max_search_passes=2)
            prior_timings = list(job.get('phase_timings', []))
            prior_metrics = dict(job.get('source_read_metrics', {}))
            job.pop('finished_at', None)
            job.update(status='running', progress='逐人邮箱未齐全，补查其他具名负责人及公开邮箱')
            original_idea = job['idea']
            job['idea'] = original_idea + ('。官网已核对的人员尚未找到具名邮箱。优先查其他目前在职、'
                '具有公开具名工作邮箱的相关负责人；不要反复查询只有传记的创始人。已查姓名：' +
                '、'.join(job['team_summary'].get('selected_names', [])))
        try:
            discovery.run_job(identifier)
        finally:
            with discovery.LOCK:
                job['idea'] = original_idea
                job['phase_timings'] = prior_timings + list(job.get('phase_timings', []))
                newer_metrics = job.get('source_read_metrics', {})
                job['source_read_metrics'] = {key:prior_metrics.get(key,0)+newer_metrics.get(key,0)
                    for key in ('network_reads','cache_hits','reused_reads')}
                # An alternate source can name an already observed person. Keep
                # the strongest complete observation once, without inventing a
                # union of fields across unverified or conflicting records.
                winners = {}
                for ri, record in enumerate(job['results']):
                    record['report'] = channel_safe(record['report'], excluded)
                    for pi, person in enumerate(record['report'].get('people', [])):
                        name = team.normalized(person.get('name',''))
                        if not name:continue
                        score = (bool(person.get('qualified')),bool(person.get('email')),
                            bool(person.get('mobile')),bool(person.get('whatsapp')))
                        if name not in winners or score > winners[name][0]:
                            winners[name] = (score,ri,pi)
                for ri, record in enumerate(job['results']):
                    record['report']['people'] = [person for pi,person in enumerate(record['report'].get('people', []))
                        if not team.normalized(person.get('name','')) or
                        winners[team.normalized(person['name'])][1:] == (ri,pi)]
                    record['report'] = channel_safe(record['report'], excluded)
                    record['verified'] = bool(record['report'].get('qualified_people'))
    try:
        if job['cancel'].is_set():
            update(status='cancelled', finished_at=time.time()); return
        update(status='running', started_at=time.time(), progress='读取官网 Contact / About / Team，确认关键人')
        began = time.monotonic()
        report = None
        try:
            report = research(job['target_website'], cancel=job['cancel'], max_seconds=45)
        except Exception as error:
            with discovery.LOCK:
                job['errors'].append('官网查询：' + str(error)[:160])
        update(phase_timings=[{'phase':'website','seconds':round(time.monotonic()-began,2)}])
        excluded = team.company_channels(report) if report else {'emails':[], 'phones':[], 'whatsapp':[], 'whatsapp_urls':[]}
        eligible = []
        if report:
            report = channel_safe(report, excluded)
            candidate = {k:'' for k in discovery.FIELDS}
            candidate.update(company=team.domain(job['target_website']), website=job['target_website'],
                contact_source=job['target_website'], fit_source=job['target_website'])
            with discovery.LOCK:
                job['results'].append(dict(candidate=candidate,report=report,verified=bool(report.get('qualified_people')),status='官网实读结果'))
            seen = set()
            for p in report.get('people', []):
                key = team.normalized(p.get('name',''))
                urls = p.get('sources',[]) + [p.get('source','')]
                urls += [ev.get('url','') for ev in p.get('evidence_by_field',{}).get('identity',[])]
                if (plausible_person_name(p.get('name','')) and p.get('title') and key not in seen and
                    not p.get('historical') and not p.get('review_required') and key_role_rank(p)<9 and
                    any(team.domain(u)==team.domain(job['target_website']) for u in urls if u)):
                    eligible.append(p); seen.add(key)
        eligible.sort(key=key_role_rank)
        update(team_summary={'mode':'official_team_then_public_sources','max_targets':3,
            'eligible_people_count':len(eligible), 'selected_names':[p['name'] for p in eligible[:3]],
            'searched_people_count':0,'fallback':not bool(eligible)})
        if job['cancel'].is_set():
            update(status='cancelled', finished_at=time.time(), progress='已停止，官网结果保留'); return
        from rate_limits import check as check_cooldown,RateLimited,details
        try:check_cooldown(job['target_website'])
        except RateLimited as limited:
            update(status='done' if job.get('results') else 'error',finished_at=time.time(),
                   stop_reason='website_cooldown',rate_limit=details(limited),
                   progress=str(limited)+' 本网站的自动模型补查未启动；其他网站继续。')
            return
        if not eligible:
            update(progress='官网没有合适具名关键人，自动补查公开展会、协会、领英等来源')
            public_fallback('no_eligible_official_person')
            return
        ordered = copy.deepcopy(report)
        keys = {team.normalized(p['name']) for p in eligible}
        ordered['people'] = copy.deepcopy(eligible) + [p for p in ordered.get('people',[]) if team.normalized(p.get('name','')) not in keys]
        child = team.start_team(job['target_website'], official_report=ordered, max_people=min(3,len(eligible)))
        child_id = child['id']
        update(team_job_id=child_id)
        stop_sent = False
        while True:
            if job['cancel'].is_set() and not stop_sent:
                team.stop_team(child_id); stop_sent=True
            snap = team.get_team(child_id)
            fresh = snap.get('report')
            with discovery.LOCK:
                if fresh:
                    safe = channel_safe(fresh, excluded)
                    job['results'][0].update(report=safe,verified=bool(safe.get('qualified_people')),status='逐人公开来源补查结果')
                job['team'] = snap
                job['team_summary']['completed_people_count'] = snap.get('completed',0)
                job['team_summary']['searched_people_count'] = snap.get('search_metrics',{}).get('ai_searches',0)
                job['team_summary']['published_people_count'] = snap.get('published_people_count',0)
                job['team_summary']['unsearched_people_count'] = snap.get('unprocessed_people_count',0)
                job['progress'] = snap.get('progress','逐人补查中')
            if snap['status'] in team.TERMINAL:
                with discovery.LOCK:
                    job['errors'].extend(snap.get('errors',[]))
                    for item in snap.get('items',[]):
                        job['errors'].extend(item.get('name','')+'：'+str(e)[:180] for e in item.get('errors',[]))
                    job['source_read_metrics'] = {key:sum(item.get('source_read_metrics',{}).get(key,0) for item in snap.get('items',[])) for key in ('network_reads','cache_hits','reused_reads')}
                update(phase_timings=job.get('phase_timings',[]) + [
                    {'phase':'named_team','seconds':round(snap.get('elapsed_seconds',0),2)}])
                if not job['cancel'].is_set() and not any(
                    record['report'].get('qualified_people') for record in job['results']):
                    public_fallback('official_people_missing_individual_email')
                else:
                    # Named-team searches already included WhatsApp. Supplement
                    # any additional qualified official cards, once per person.
                    searched=[item.get('name','') for item in snap.get('items',[])
                        if item.get('started_at') and item.get('status') in team.TERMINAL]
                    started=time.monotonic()
                    completion=complete_qualified_channels(job['results'],job['cancel'],update,
                        excluded_channels=excluded,skip_names=searched,max_people=5)
                    completion['named_person_searches_already_included_whatsapp']=searched
                    with discovery.LOCK:
                        job['channel_completion_summary']=completion
                        job['phase_timings'].append({'phase':'remaining_person_channels','seconds':round(time.monotonic()-started,2)})
                        for record in job['results']:
                            record['report']=channel_safe(record['report'],excluded)
                            record['verified']=bool(record['report'].get('qualified_people'))
                    update(status='cancelled' if job['cancel'].is_set() else snap['status'],finished_at=time.time())
                return
            time.sleep(.1)
    except Exception as error:
        with discovery.LOCK:
            job['errors'].append('关键人补查：'+str(error)[:200])
        update(status='cancelled' if job['cancel'].is_set() else ('done' if job['results'] else 'error'),
            finished_at=time.time(), progress='已保留实读结果；补查未完成')
    finally:
        if child_id and job['cancel'].is_set():
            try:team.stop_team(child_id)
            except ValueError:pass


def complete_qualified_channels(records,cancel,progress,**kwargs):
    """Public callable for fresh full batches or explicitly revalidated snapshots."""
    from channel_completion import complete_qualified_records
    return complete_qualified_records(records,cancel,progress,**kwargs)
