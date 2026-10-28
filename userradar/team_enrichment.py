"""Bounded, read-only enrichment of identities independently published by a website."""
import copy
import json
from pathlib import Path
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

JOBS = {}
LOCK = threading.RLock()
COORDINATORS = ThreadPoolExecutor(max_workers=4, thread_name_prefix='radar-team')
PEOPLE = ThreadPoolExecutor(max_workers=3, thread_name_prefix='radar-person')
TERMINAL = {'done', 'cancelled', 'error'}
MAX_PEOPLE = 30
ROOT = Path(__file__).resolve().parent


def normalized(value):
    from enrichment import norm
    return norm(value)


def domain(value):
    return (urlsplit(value).hostname or '').lower().removeprefix('www.')


def snapshot(job):
    out = copy.deepcopy({k: v for k, v in job.items() if k != 'cancel'})
    out['elapsed_seconds'] = round(max(0, (out.get('finished_at') or time.time()) - out['queued_at']), 2)
    out['completed'] = sum(item['status'] in TERMINAL for item in out['items'])
    out['total'] = len(out['items'])
    return out


def get_team(identifier):
    with LOCK:
        if identifier not in JOBS:
            raise ValueError('逐人补查记录不存在，请重新开始')
        return snapshot(JOBS[identifier])


def start_team(website,*,official_report=None,max_people=None,core_only=False,max_seconds=180):
    if max_people is None:max_people=3 if core_only else MAX_PEOPLE
    if not isinstance(website, str) or not website.strip() or len(website) > 2000:
        raise ValueError('请填写公司官网地址')
    if isinstance(max_people,bool) or not isinstance(max_people,int) or not 1<=max_people<=MAX_PEOPLE:
        raise ValueError('逐人补查人数上限无效')
    if isinstance(max_seconds,bool) or not isinstance(max_seconds,(int,float)) or not 0<max_seconds<=180:
        raise ValueError('核心补查时间上限无效')
    if official_report is not None and (not isinstance(official_report,dict) or domain(official_report.get('website',''))!=domain(website.strip() if '://' in website else 'https://'+website.strip())):
        raise ValueError('内部官网报告与目标公司不一致')
    from app import public_url
    from request_budget import request_scope
    with request_scope(seconds=10):
        website = public_url(website.strip() if '://' in website else 'https://' + website.strip())
    with LOCK:
        if sum(j['status'] not in TERMINAL or j.get('worker_pending',False) for j in JOBS.values()) >= 4:
            raise ValueError('逐人补查任务较多，请等待或停止一个任务后重试')
        for key in list(JOBS):
            if len(JOBS) < 20:
                break
            if JOBS[key]['status'] in TERMINAL and not JOBS[key].get('worker_pending'):
                JOBS.pop(key)
        identifier = uuid.uuid4().hex
        JOBS[identifier] = dict(id=identifier, website=website, status='queued',core_only=bool(core_only),max_seconds=max_seconds,
            progress='等待读取官网 Contact / About / Team 页面', queued_at=time.time(),
            report=None, items=[], errors=[], cancel=threading.Event(),
            search_metrics={'ai_searches': 0, 'candidates': 0, 'rejected_identity': 0})
        if core_only:JOBS[identifier]['worker_pending']=True
        COORDINATORS.submit(run_team, identifier, copy.deepcopy(official_report), max_people)
    return {'id': identifier}


def stop_team(identifier):
    with LOCK:
        job = JOBS.get(identifier)
        if job is None:
            raise ValueError('逐人补查记录不存在')
        if job['status'] not in TERMINAL:
            job['cancel'].set()
            job['status'] = 'stopping'
            job['progress'] = '正在停止；已核实字段保留，缺项留空'
    return get_team(identifier)


def company_channels(report):
    """Page-wide channels cannot become personal by repetition in an AI answer."""
    from contact_quality import phone_info
    from app import is_role
    from enrichment import brand_mailbox
    people = report.get('people', [])
    website = report.get('website', '')
    assigned_emails = {x.strip().casefold() for p in people for x in p.get('email', '').split(';') if x.strip()}
    assigned_emails = {address for address in assigned_emails if not is_role(address) and not brand_mailbox(address, domain(website), website)}
    assigned_phones = {phone_info(p.get('phone', ''), p.get('country_hint'))['phone_e164'] for p in people if p.get('evidence_by_field', {}).get('phone')}
    assigned_wa = {w.get('phone', '') for p in people for w in p.get('whatsapp', []) if w.get('attribution') == 'person'}
    assigned_urls = {w.get('url', '') for p in people for w in p.get('whatsapp', []) if w.get('attribution') == 'person'}
    mail = {str(x.get('email', '') if isinstance(x, dict) else x).strip().casefold() for x in report.get('emails', [])}
    phones = {phone_info(x.get('phone', '') if isinstance(x, dict) else x)['phone_e164'] for x in report.get('phones', [])}
    wa = {phone_info(x.get('phone', ''))['phone_e164'] for x in report.get('whatsapp', []) if isinstance(x, dict)}
    return {'emails': sorted(mail - assigned_emails - {''}),
            'phones': sorted((phones | wa) - assigned_phones - assigned_wa - {''}),
            'whatsapp': sorted(wa - assigned_wa - {''}),
            'whatsapp_urls': sorted({x.get('url', '') for x in report.get('whatsapp', []) if isinstance(x, dict)} - assigned_urls - {''})}


def remove_company_channels(person, excluded):
    from contact_quality import phone_info
    p = copy.deepcopy(person)
    fields = p.setdefault('evidence_by_field', {})
    reasons = []
    if p.get('email', '').strip().casefold() in excluded['emails']:
        p['email'] = ''; fields.pop('email', None); reasons.append('邮箱与官网公司公共邮箱相同')
    blocked = set(excluded['phones']) | set(excluded['whatsapp'])
    if phone_info(p.get('phone', ''), p.get('country_hint'))['phone_e164'] in blocked:
        p.update(phone='', phone_raw='', mobile='', phone_e164=''); fields.pop('phone', None)
        reasons.append('号码与官网公司公共电话或 WhatsApp 相同')
    blocked_urls = set(excluded.get('whatsapp_urls', []))
    p['explicit_whatsapp'] = [w for w in p.get('explicit_whatsapp', []) if phone_info(w.get('phone', ''))['phone_e164'] not in blocked and w.get('url', '') not in blocked_urls]
    p['whatsapp'] = [w for w in p.get('whatsapp', []) if phone_info(w.get('phone', ''))['phone_e164'] not in blocked and w.get('url', '') not in blocked_urls]
    if not p['explicit_whatsapp'] and not p['whatsapp']:
        fields.pop('whatsapp', None)
    if reasons:
        p['company_channel_exclusions'] = reasons
    return p


def brief_for(website, person, excluded=None,*,core_only=False):
    brief=('逐人公开商务联系方式补查。仅查指定公司官网 ' + website + ' 的这个已由应用独立读取官网确认的人员：' +
        json.dumps({'name': person['name'], 'title': person['title']}, ensure_ascii=False) +
        '。姓名和官网原始职位不能替换，不要返回同名其他公司人员或其他同事。包括工程师、销售经理等官网团队成员，本轮不限制采购职位。'
        '最多 5 个精准搜索，依次官网具名卡片/公开 PDF、本人公开 LinkedIn 页面或专业帖子、近期展会/协会/合作伙伴公开资料。'
        '搜索完整姓名 + 公司/域名 + email；完整姓名 + 职位 + 手机/WhatsApp；读取原始页面。每个人只进行这一轮补查。'
        '邮箱、本人手机、本人 WhatsApp 可在本轮同时查，缺项留空。全部联系方式必须原文明确属于此完整姓名且与这家公司关联。'
        'LinkedIn 索引或登录墙只作为线索，不能算独立读取。不能猜邮箱格式、拼姓名、推算 WhatsApp、查询注册或发消息。'
        '禁止返回公司公共邮箱、客服 WhatsApp、前台/总机、同事号码；即便同页出现也不能分配给个人。'
        '请保留完整姓名和官网原始职位，website 和 fit_source 必须属于指定官网；每个字段附原始证据 URL 和短引文。'
        '没有任何公开渠道也返回空列表与简短说明，不要编造。以下是本轮官网实读的公司公共渠道，禁止当作该人的联系方式：' + json.dumps(excluded or {}, ensure_ascii=False))
    if core_only:
        from channel_completion import missing_fields
        brief=brief.replace('最多 5 个精准搜索','最多 3 个精准搜索').replace('完整姓名 + 职位 + 手机/WhatsApp','完整姓名 + 公司 + 本人公开商务电话（直线座机也可）').replace('邮箱、本人手机、本人 WhatsApp 可在本轮同时查','仅补查缺失邮箱、本人公开商务电话；WhatsApp 仅顺带收录，不为它搜索')
        brief+='本轮缺项：'+ '、'.join(missing_fields(person,core_only=True))+'。已经由原文核实的字段不要重新广泛搜索。'
    return brief


def _score(person,*,core_only=False):
    return (bool(person.get('email')), bool(person.get('phone_e164') or person.get('mobile')) if core_only else bool(person.get('mobile')), bool(person.get('whatsapp')), len(person.get('sources', [])))


def enrich_person(job, index, official, excluded):
    from ai_discovery import discover, valid_candidate
    from enrichment import verify_candidate
    from public_sources import SourceReader
    item = job['items'][index]
    cancel = job['cancel']
    def update(**changes):
        with LOCK:
            item.update(changes)
    def search_progress(**changes):
        if job.get('core_only') and changes.get('ai_usage') is not None:
            from ai_discovery import merge_ai_usage
            with LOCK:
                merge_ai_usage(job,changes['ai_usage'])
                merge_ai_usage(item,changes['ai_usage'])
    if cancel.is_set():
        update(status='cancelled', progress='已停止，缺项留空'); return
    if job.get('core_only'):
        from contact_progress import core_person
        from contact_quality import qualify
        from app import is_role
        # Excluding a company mailbox/phone may invalidate a flag copied from
        # the original report. Recompute before deciding to skip this person.
        with LOCK:qualify({'people':item['people']},is_role)
        if core_person(item['people'][0]):
            update(status='done', progress='核心商务字段已齐全；WhatsApp 缺失不追加搜索',finished_at=time.time(),elapsed_seconds=0)
            return
    began = time.monotonic()
    folder = ROOT / 'research-runs' / ('team-' + job['id']) / ('person-%02d' % (index + 1))
    folder.mkdir(parents=True, exist_ok=True)
    try:
        update(status='running', started_at=time.time(), progress='补查本人公开邮箱与商务电话' if job.get('core_only') else '补查本人公开邮箱、手机与 WhatsApp')
        with LOCK:
            job['search_metrics']['ai_searches'] += 1
        core_kwargs={'core_only':True} if job.get('core_only') else {}
        answer = discover(brief_for(job['website'], official, excluded,**core_kwargs), cancel, search_progress, evidence_dir=folder, named_team={'name': official['name'], 'title': official['title'], 'website': job['website'], 'company': domain(job['website'])},**core_kwargs)
        update(notes=str(answer.get('notes', ''))[:2000])
        if cancel.is_set():
            update(status='cancelled', progress='已停止，已核实字段保留'); return
        reader = SourceReader(folder=folder / 'sources', cancel=cancel)
        strongest = copy.deepcopy(item['people'][0])
        checks = []; accepted = []; rejected = 0
        for candidate in answer.get('companies', [])[:3]:
            if cancel.is_set(): break
            with LOCK:
                job['search_metrics']['candidates'] += 1
            if isinstance(candidate, dict):
                candidate = dict(candidate)
                # An identity-only search can honestly omit contact_source. The
                # already-read official card supplies an identity URL, never
                # evidence of an email or phone; invalid nonblank URLs stay invalid.
                for key in ('contact_source', 'fit_source'):
                    if candidate.get(key) == '':
                        candidate[key] = official.get('source', '')
            if (not valid_candidate(candidate) or domain(candidate.get('website', '')) != domain(job['website']) or
                    normalized(candidate.get('name', '')) != normalized(official['name'])):
                rejected += 1
                continue
            # Search aliases cannot change the canonical name or published title.
            candidate = dict(candidate, name=official['name'], title=official['title'], website=job['website'])
            official_sources = [ev.get('url', '') for ev in official.get('evidence_by_field', {}).get('identity', [])] + official.get('sources', []) + [official.get('source', '')]
            identity_url = next((u for u in official_sources if u and domain(u) == domain(job['website'])), '')
            original_sources = [s for s in candidate.get('sources', []) if s.get('url') != identity_url]
            candidate['sources'] = ([{'url': identity_url, 'kind': 'official', 'purposes': ['identity'], 'quote': ''}] if identity_url else []) + original_sources[:5]
            person = verify_candidate(candidate, reader, published_identity=official, excluded_channels=excluded)
            person = remove_company_channels(person, excluded)
            person['name'] = official['name']; person['title'] = official['title']
            checks.extend(person.get('source_checks', []))
            accepted.append(candidate)
            from app import is_role
            from contact_quality import qualify
            qualify({'people': [person]}, is_role)
            if _score(person,core_only=job.get('core_only',False)) > _score(strongest,core_only=job.get('core_only',False)):
                strongest = person
            elif person.get('linkedin_url'):
                strongest['linkedin_url'] = person['linkedin_url']
                strongest['linkedin_note'] = person.get('linkedin_note', '公开搜索索引线索；未独立读取确认')
            strongest['source_checks'] = copy.deepcopy(checks)
            with LOCK:
                item.update(people=[strongest], source_checks=copy.deepcopy(checks), candidates=copy.deepcopy(accepted))
                _refresh(job)
        with LOCK:
            job['search_metrics']['rejected_identity'] += rejected
        update(status='cancelled' if cancel.is_set() else 'done',
            progress='已停止，已核实字段保留' if cancel.is_set() else '公开来源核对完成，缺项留空',
            rejected_identity=rejected, source_checks=checks, candidates=accepted,
            source_read_metrics=copy.deepcopy(reader.read_metrics))
    except Exception as error:
        with LOCK:
            item.setdefault('errors', []).append(str(error)[:240])
        update(status='cancelled' if cancel.is_set() else 'error', error=str(error)[:240], progress='已停止' if cancel.is_set() else '本人的补查失败，官网身份与已有字段保留')
    finally:
        update(finished_at=time.time(), elapsed_seconds=round(time.monotonic() - began, 2))
        with LOCK:
            _refresh(job)


def _refresh(job):
    if not job.get('report'): return
    from app import is_role
    from contact_quality import qualify
    job['report']['people'] = [copy.deepcopy(item['people'][0]) for item in job['items'] if item['people']] + copy.deepcopy(job.get('unprocessed_identities', []))
    qualify(job['report'], is_role)
    from contact_progress import mark_progress
    mark_progress(job['report'])
    done = sum(item['status'] in TERMINAL for item in job['items'])
    job['progress'] = '已完成 %s/%s 位公开团队成员补查；缺项留空' % (done, len(job['items']))


def run_team(identifier,official_report=None,max_people=None):
    from ai_discovery import CoreDeadline
    from request_budget import request_scope
    job=JOBS[identifier]
    with CoreDeadline(job,LOCK):
        with request_scope(seconds=job.get('max_seconds',180) if job.get('core_only') else None):
            return _run_team(identifier,official_report,max_people)


def _run_team(identifier,official_report=None,max_people=None):
    if max_people is None:max_people=3 if JOBS[identifier].get('core_only') else MAX_PEOPLE
    from app import research
    from person_identity import plausible_person_name
    job = JOBS[identifier]
    try:
        with LOCK:
            if job['cancel'].is_set():
                job.update(status='cancelled', finished_at=time.time()); return
            job.update(status='running', started_at=time.time(), progress='先独立读取官网 Contact / About / Team 确认姓名和职位')
        # Only trusted server callers may reuse their immediately preceding read.
        # HTTP may select an existing server job, never submit a client report.
        report = copy.deepcopy(official_report) if official_report is not None else research(job['website'], cancel=job['cancel'], max_seconds=45)
        if domain(report.get('website',''))!=domain(job['website']):raise ValueError('内部官网报告域名不一致')
        excluded = company_channels(report)
        people = []; seen = set()
        for person in report.get('people', []):
            key = normalized(person.get('name', ''))
            if not plausible_person_name(person.get('name', '')) or not person.get('title') or key in seen: continue
            # A server-side official read is mandatory; client submitted identities
            # and previous runs never enter this queue.
            sources = person.get('sources', []) + [person.get('source', '')]
            sources += [ev.get('url', '') for ev in person.get('evidence_by_field', {}).get('identity', [])]
            if not any(domain(url) == domain(job['website']) for url in sources if url): continue
            canonical = copy.deepcopy(person)
            if not canonical.get('evidence_by_field', {}).get('identity'):
                from enrichment import contains, title_matches
                text = canonical.get('evidence', '')
                source = canonical.get('source', '')
                if domain(source) == domain(job['website']) and contains(text, canonical['name']) and title_matches(text, canonical['title']):
                    canonical.setdefault('evidence_by_field', {})['identity'] = [{'url': source, 'quote': text, 'checked_at': report.get('checked_at', ''), 'source_type': 'official'}]
            seen.add(key)
            people.append(canonical)
        with LOCK:
            job['official_report_reused']=official_report is not None
            job['published_people_count'] = len(people)
            job['unprocessed_people_count'] = max(0, len(people) - max_people)
            job['unprocessed_identities'] = [dict(remove_company_channels(p, excluded), team_enrichment_status='本轮超过 %s 人补查上限，未补查'%max_people) for p in people[max_people:]]
            job['excluded_channels'] = excluded
            job['report'] = copy.deepcopy(report)
            job['items'] = [dict(name=p['name'], title=p['title'], status='queued', people=[remove_company_channels(p, excluded)], source_checks=[], progress='等待逐人补查') for p in people[:max_people]]
            _refresh(job)
        futures = [PEOPLE.submit(enrich_person, job, i, p, excluded) for i, p in enumerate(people[:max_people])]
        for future in as_completed(futures):
            future.result()
        with LOCK:
            job.update(status='cancelled' if job['cancel'].is_set() else 'done', finished_at=time.time())
            _refresh(job)
            if not people: job['progress'] = '官网未确认完整姓名和职位，未启动逐人补查'
    except Exception as error:
        with LOCK:
            job['errors'].append(str(error)[:240])
            job.update(status='cancelled' if job['cancel'].is_set() else 'error', finished_at=time.time(), progress='查询已停止' if job['cancel'].is_set() else '官网读取失败，未使用客户端或旧名单')
