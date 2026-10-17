"""Bounded completion of a source-verified identity; unknown channels stay empty."""
import json
from pathlib import Path
from person_identity import plausible_person_name

def missing_fields(person,*,core_only=False):
    if core_only:
        return (["具名本人工作邮箱"] if not person.get('email') else []) + (["本人公开商务电话（直线座机或手机）"] if not (person.get('phone_e164') or person.get('mobile')) else [])
    return [label for key,label in [('email','具名本人工作邮箱'),('mobile','近期本人商务手机'),('whatsapp','明确本人WhatsApp')] if not person.get(key)]

def eligible(person,*,core_only=False):
    return bool(plausible_person_name(person.get('name','')) and person.get('title') and person.get('evidence_by_field',{}).get('identity') and not person.get('historical') and not person.get('review_required') and missing_fields(person,core_only=core_only))

def complete_channels(candidate,person,cancel,progress,discover,evidence_dir=None,source_reader=None,*,core_only=False,excluded_channels=None):
    from enrichment import norm,verify_candidate
    from public_sources import SourceReader
    from app import host
    if not eligible(person,core_only=core_only) or cancel.is_set():return None
    missing=missing_fields(person,core_only=core_only)
    attempt={'missing':missing,'status':'searching','source_checks':[]}
    person['channel_completion']=attempt
    identity={k:person.get(k,'') for k in ('name','title','email','mobile')}
    identity.update(company=candidate['company'],website=candidate['website'])
    brief='只补查这个已由原文核对身份的同一个人的缺失商务联系字段：'+ '、'.join(missing)+'。'+json.dumps(identity,ensure_ascii=False)+'''\n已知字段只用于辨认同一人，不能用来推算缺失字段。检索完整姓名+WhatsApp/wa.me，已知商务号码/邮箱+WhatsApp，本人职业帖子、公开商务名片、展会/协会/政府名录。邮箱必须原文明示归给此人；公司客服号码、品牌共享邮箱、其他同名者或同事资料均拒绝。号码不能推定WhatsApp，不构造wa.me，不探测注册状态，不登录、不发消息、不使用数据经纪商。返回缺项为空也可以；索引不可读时仅作为线索，保留原始来源和限制。优先近期依据。'''
    if core_only:
        brief=brief.replace('检索完整姓名+WhatsApp/wa.me，已知商务号码/邮箱+WhatsApp，',
                            '最多 3 个精准搜索，只检索完整姓名+公司+缺失工作邮箱或本人公开商务电话，直线座机也可；不为 WhatsApp 追加搜索。可查')
    try:
        search_kwargs={'core_only':True} if core_only else {}
        found=discover(brief,cancel,progress,evidence_dir=evidence_dir,**search_kwargs)
        attempt['search_note']=found.get('notes','')[:1200]
        # Keep one independently read source per known field, leaving room for
        # newly discovered originals under the six-source verification limit.
        basis=[]
        for field in ('identity','email','phone','whatsapp','work_domain'):
            for ev in person.get('evidence_by_field',{}).get(field,[])[:1]:
                if ev.get('url'):basis.append({'url':ev['url'],'kind':'public','purposes':[field],'quote':ev.get('quote','')})
        folder=Path(evidence_dir)/'sources' if evidence_dir else None
        reader=source_reader.fork(folder=folder,cancel=cancel) if source_reader is not None else SourceReader(folder,cancel=cancel)
        matched=False
        for item in found.get('companies',[])[:3]:
            if cancel.is_set():break
            if norm(item.get('name'))!=norm(person['name']) or host(item.get('website',''))!=host(candidate['website']):continue
            matched=True
            c=dict(item,company=candidate['company'],website=candidate['website'],name=person['name'],title=person['title'])
            c['email']=person.get('email') or item.get('email','')
            c['phone']=person.get('phone') or person.get('mobile') or item.get('phone','')
            c['sources']=list({s['url']:s for s in basis+item.get('sources',[])}.values())[:6]
            updated=verify_candidate(c,reader,excluded_channels=excluded_channels)
            attempt['source_checks'].extend(updated.get('source_checks',[]))
            attempt['read_metrics']=getattr(reader,'read_metrics',{})
            # A failed/new source may never remove already verified fields.
            if person.get('qualified') and not updated.get('qualified'):continue
            if person.get('email') and updated.get('email')!=person['email']:continue
            if person.get('mobile') and updated.get('mobile')!=person['mobile']:continue
            if core_only and person.get('phone_e164') and updated.get('phone_e164')!=person['phone_e164']:continue
            old_wa={(w.get('phone'),w.get('url')) for w in person.get('whatsapp',[])}
            new_wa={(w.get('phone'),w.get('url')) for w in updated.get('whatsapp',[])}
            if not old_wa.issubset(new_wa):continue
            gains=[label for key,label in [('email','具名本人工作邮箱'),('mobile','近期本人商务手机'),('whatsapp','明确本人WhatsApp')] if not person.get(key) and updated.get(key)]
            if core_only:
                gains=[label for label in missing if label not in missing_fields(updated,core_only=True)]
            if gains:
                attempt.update(status='improved',gained=gains)
                updated['channel_completion']=attempt
                return updated
        attempt['access_limited']=any(s.get('status')!='已独立读取' or s.get('channel_note') for s in attempt['source_checks'])
        attempt['status']='cancelled' if cancel.is_set() else 'no_verified_addition' if matched else 'no_matching_public_candidate'
        return None
    except Exception as error:
        attempt.update(status='cancelled' if cancel.is_set() else 'incomplete',error=str(error)[:250])
        raise
    finally:
        if evidence_dir:
            folder=Path(evidence_dir);folder.mkdir(parents=True,exist_ok=True)
            (folder/'completion-attempt.json').write_text(json.dumps(attempt,ensure_ascii=False,indent=2))


def evidence_sources(person):
    """Keep provenance for independent rereads, including official domain proof."""
    sources=[]
    for field in ('identity','email','phone','whatsapp','work_domain'):
        for evidence in person.get('evidence_by_field',{}).get(field,[])[:1]:
            if evidence.get('url'):
                sources.append(dict(url=evidence['url'],kind='public',purposes=[field],quote=evidence.get('quote','')))
    return list({source['url']:source for source in sources}.values())[:6]



class _InvocationSources:
    """Share only successful original documents for this helper call."""
    def __init__(self):
        import threading
        self.documents={};self.lock=threading.RLock()
    def wrap(self,reader,*,cache_only=False):
        pool=self
        class SharedReader:
            def __init__(self,base):self.base=base;self.cache_only=cache_only
            @property
            def read_metrics(self):return getattr(self.base,'read_metrics',{})
            def read(self,url):
                import copy,time
                cancel=getattr(self.base,'cancel',None)
                if cancel is not None and cancel.is_set():raise ValueError('查询已停止')
                if time.monotonic()>getattr(self.base,'deadline',float('inf')):raise ValueError('本轮来源核对达到时间上限')
                with pool.lock:cached=copy.deepcopy(pool.documents.get(url))
                if cached is not None:
                    metrics=getattr(self.base,'read_metrics',None)
                    if metrics is not None:metrics['reused_reads']=metrics.get('reused_reads',0)+1
                    folder=getattr(self.base,'folder',None)
                    if folder:
                        import hashlib
                        Path(folder).mkdir(parents=True,exist_ok=True)
                        (Path(folder)/(hashlib.sha256(url.encode()).hexdigest()[:20]+'.json')).write_text(json.dumps(cached,ensure_ascii=False,indent=2))
                    return cached
                if self.cache_only:raise ValueError('本轮尚未成功读取该原始来源；不追加网络重试')
                document=self.base.read(url)
                if isinstance(document,dict) and 'error' not in document:
                    with pool.lock:pool.documents[url]=copy.deepcopy(document)
                return document
            def fork(self,folder=None,cancel=None):
                return pool.wrap(self.base.fork(folder=folder,cancel=cancel),cache_only=self.cache_only)
        return SharedReader(reader)
    def has_all(self,urls):
        with self.lock:return bool(urls) and all(url in self.documents for url in urls)


def complete_qualified_records(records,cancel,progress,*,discover=None,excluded_channels=None,
        skip_names=(),max_people=5,revalidate=False,force=False,evidence_dir=None,core_only=False):
    """Bounded full-mode person supplement; saved snapshots must be revalidated.

    Mutates records with independently verified replacements and attempt metadata.
    Returns person-level metrics. The provider retains its global AI-slot limit.
    """
    import copy
    from concurrent.futures import ThreadPoolExecutor
    from enrichment import norm,verify_candidate
    from public_sources import SourceReader
    from app import host,is_role
    from contact_quality import qualify
    if discover is None:
        from ai_discovery import discover
    summary={'attempted':[],'skipped':[],'improved':[],'errors':[],'read_metrics':{}}
    if core_only:return summary
    skip={norm(name) for name in skip_names}
    selected=[];seen=set();counts={}
    for record in records:
        for index,person in enumerate(record.get('report',{}).get('people',[])):
            candidate=record.get('candidate',{})
            website=candidate.get('website') or record['report'].get('website','')
            key=(host(website),norm(person.get('name','')))
            if key in seen or not person.get('qualified') or person.get('whatsapp'):continue
            seen.add(key)
            if not eligible(person):continue
            reason=''
            if norm(person['name']) in skip:reason='already_named_person_search'
            elif not force and person.get('channel_completion'):reason='already_channel_search'
            elif not force and 'whatsapp' in person.get('named_email_completion',{}).get('searched_fields',[]):reason='already_named_all_channel_search'
            elif counts.get(key[0],0)>=max(0,min(5,int(max_people))):reason='company_person_limit'
            if reason:
                summary['skipped'].append({'name':person['name'],'website':website,'reason':reason});continue
            counts[key[0]]=counts.get(key[0],0)+1
            candidate=dict(candidate,website=website,company=candidate.get('company') or host(website))
            selected.append((record,index,copy.deepcopy(person),candidate))
    shared_sources=_InvocationSources()
    def run(entry,cache_only=False):
        record,index,person,candidate=entry
        name=person['name']
        folder=Path(evidence_dir)/('person-%02d'%(selected.index(entry)+1)) if evidence_dir else None
        if cancel.is_set():return entry,None,{'name':name,'status':'cancelled'}
        reader=shared_sources.wrap(SourceReader(folder=folder/'sources' if folder else None,cancel=cancel),cache_only=cache_only)
        try:
            if revalidate:
                check=dict(candidate,name=name,title=person['title'],email=person.get('email',''),
                    phone=person.get('phone') or person.get('mobile',''),sources=evidence_sources(person))
                person=verify_candidate(check,reader,excluded_channels=excluded_channels)
                if not person.get('qualified'):
                    person['channel_completion']={'status':'fresh_identity_or_email_unconfirmed','source_checks':person.get('source_checks',[])}
                    return entry,person,dict(name=name,status='fresh_identity_or_email_unconfirmed')
            reader.cache_only=False
            progress(progress='逐人补查本人 WhatsApp：'+name)
            updated=complete_channels(candidate,person,cancel,progress,discover,evidence_dir=folder,
                source_reader=reader,excluded_channels=excluded_channels)
            result=updated or person
            attempt=result.get('channel_completion',{})
            return entry,result,dict(name=name,status=attempt.get('status','not_started'),
                gained=attempt.get('gained',[]),source_checks=attempt.get('source_checks',[]),read_metrics=getattr(reader,'read_metrics',{}))
        except Exception as error:
            return entry,person,dict(name=name,status='incomplete',error=str(error)[:240])
    with ThreadPoolExecutor(max_workers=min(3,len(selected) or 1)) as pool:
        outcomes=list(pool.map(run,selected))
    # A peer may finish reading the missing shared company/domain proof after
    # this person's first check. Retry verification once, using only documents
    # successfully read during this invocation; failed reads never trigger IO.
    if revalidate and not cancel.is_set():
        for index,(entry,person,attempt) in enumerate(outcomes):
            if attempt.get('status')!='fresh_identity_or_email_unconfirmed':continue
            urls=[source['url'] for source in evidence_sources(entry[2])]
            if not shared_sources.has_all(urls):continue
            retried=run(entry,cache_only=True)
            retried[2]['fresh_shared_document_retry']=True
            outcomes[index]=retried
    for (record,index,old,candidate),person,attempt in outcomes:
        summary['attempted'].append(attempt)
        if person is not None:record['report']['people'][index]=person
        for metric,value in attempt.get('read_metrics',{}).items():
            summary['read_metrics'][metric]=summary['read_metrics'].get(metric,0)+value
        if attempt.get('gained'):summary['improved'].append(attempt['name'])
        if attempt.get('error'):summary['errors'].append(attempt)
    for record in records:
        qualify(record['report'],is_role)
        record['verified']=bool(record['report'].get('qualified_people'))
    return summary
