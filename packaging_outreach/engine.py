"""Resumable stages with concurrent independent customers and one sender per brand."""
import base64,hashlib,json,time,uuid,threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from . import sources,materials,prompts,mail,profiles,performance,sales
from .cache import PageCache
from .providers import HTTPProvider,RetryLater,UncertainCall
from .images import validate_png
from .store import Store

class Engine:
    def __init__(self,config,provider=None,fetcher=None):
        self.config=config;self.store=Store(config['workspace']);self.provider=provider or HTTPProvider(config)
        self.fetcher=PageCache(config['workspace'],fetcher or sources.fetch_public,config.get('performance',{}).get('page_cache_seconds',900));self.brands={b['id']:b for b in config['brands']}
        self.gates={k:threading.BoundedSemaphore(n) for k,n in dict(research=1,text=2,image=2).items()}
        for k,n in config.get('provider_concurrency',{}).items():self.gates[k]=threading.BoundedSemaphore(n)
    def api(self,job,stage,prompt,data,images=()):
        def call(rid):
            with self.gates['research' if stage=='research' else 'image' if stage=='image' else 'text']:
                return self.provider.call(stage,prompt,data,rid,images)
        return self.store.cached_call(job['id'],stage,call)
    def status(self):
        result=self.store.status();result['performance']=performance.report(self.store,self.config.get('performance',{}).get('target_seconds',300))
        status=self.store.setting('worker_status');result['worker']=json.loads(status) if status else None
        return result
    def reference(self,p):
        url=p['product_reference']['url'];host=sources.host(url)
        if host not in {sources.host(p['company_url']),'cdn.shopify.com'}:raise ValueError('Reference host must be official or approved Shopify CDN')
        path=self.store.root/'references';path.mkdir(exist_ok=True);key=hashlib.sha256(url.encode()).hexdigest()
        meta=path/(key+'.json')
        if meta.exists():
            saved=json.loads(meta.read_text());raw=(path/saved['file']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=saved['sha256']:raise ValueError('Product reference changed')
            return raw,saved['mime']
        u=urlsplit(url);conn=sources.PinnedHTTPS(u.hostname,timeout=20)
        try:
            conn.request('GET',u.path+('?' +u.query if u.query else ''),headers={'User-Agent':'Packaging-Outreach/0.1'})
            response=conn.getresponse()
            if response.status!=200:raise ValueError('Product image unavailable; exact reference URL required')
            raw=response.read(8*1024*1024+1)
        finally:conn.close()
        if len(raw)>8*1024*1024:raise ValueError('Product reference too large')
        mime='image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg' if raw.startswith(b'\xff\xd8') else 'image/webp' if raw[:4]==b'RIFF' and raw[8:12]==b'WEBP' else None
        if not mime:raise ValueError('Unsupported product reference')
        filename=key+'.image';(path/filename).write_bytes(raw)
        meta.write_text(json.dumps({'file':filename,'sha256':hashlib.sha256(raw).hexdigest(),'mime':mime}))
        return raw,mime
    def verify(self,candidate,pages,brand=None):
        urls=list(dict.fromkeys(candidate[k] for k in ('company_url','email_source_url','product_evidence_url')));allowed={sources.host(candidate['company_url'])}
        browser=self.config.get('source_mode')=='browser_excerpts'
        if browser:
            collected={p['url']:{'url':p['url'],'text':p['text'],'sha256':hashlib.sha256(p['text'].encode()).hexdigest(),'checked_at':sources.NOW().isoformat(),'provenance':'official_subscription_browser_excerpt'} for p in pages if len(p['text'].split())<=200}
        else:
            with ThreadPoolExecutor(max_workers=3) as pool:collected=dict(zip(urls,pool.map(lambda u:self.fetcher(u,allowed),urls)))
        profile=profiles.resolve(self.config,brand)
        result=sources.verify_candidate(candidate,{'constraints':{},'price_policy':profile['price_policy']},lambda url,hosts:collected[url],allow_browser=browser)
        product=collected[candidate['product_evidence_url']];image=candidate['product_image_url'];count=candidate['unit_count'];quote=candidate['count_evidence_quote']
        if image not in product.get('images',[]) and image not in product['text']:raise ValueError('Product image URL not bound to source page')
        if type(count) is not int or not 1<=count<=50 or not quote or sources.normalize(quote) not in sources.normalize(product['text']):raise ValueError('Product quantity needs source evidence')
        p=result['payload'];profiles.apply_price_tier(p,profile);p.update(company=result['company'],recipient=result['recipient'],product_reference={'url':image,'source_url':p['product_evidence_url'],'unit_count':count,'count_evidence_quote':quote},source_mode=self.config.get('source_mode','direct_https'),seller_profile=profile)
        p['workflow_mode']=self.config.get('workflow',{}).get('mode','balanced')
        return p
    def process(self,jid):
        if not self.store.claim(jid):return
        job=None
        try:
            job=self.store.get(jid);p=job['payload'];brand=self.brands[job['brand']]
            stage=job['stage']
            if stage=='research':
                profile=profiles.resolve(self.config,brand)
                with self.store.db() as c:
                    excluded=[r[0] for r in c.execute("SELECT DISTINCT company_key FROM jobs WHERE company_key!=''")]
                    recipients=[r[0] for r in c.execute('SELECT DISTINCT recipient FROM events')]
                    timing=c.execute('SELECT origin FROM timing WHERE job_id=?',(jid,)).fetchone()
                target=brand.get('target',self.config.get('target',profile['target']))
                result=self.api(job,'research',prompts.RESEARCH_PROFILE,{'target':target,'seller_offer':profile['offer'],'price_policy':profile['price_policy'],'excluded_company_domains':excluded,'excluded_recipients':recipients})
                candidate=result.get('candidate')
                added=None
                if candidate:
                    # Skip known domains before HTTP, planning or image spend.
                    if sources.host(candidate['company_url']) not in excluded and candidate['recipient'].lower() not in recipients:
                        verified=self.verify(candidate,result.get('pages',[]),brand);added=self.store.add(job['brand'],verified,'concept',origin=timing['origin'] if timing else None)
                if not added:self.store.setting('discovery_next_at',time.time()+30)
                self.store.advance(jid,'done',{'candidate_found':bool(candidate),'new_job_id':added},'done');return
            if stage=='concept':
                public={k:p[k] for k in ['company','facts','product_evidence_url','product_reference']}
                base_profile=p.get('seller_profile') or profiles.resolve(self.config,brand);profile=profiles.for_payload(base_profile,p);public['seller_profile']=profiles.public(profile);p['seller_profile']=profile
                for key in ('retail_price','packaging_tier','minimum_order_quantity','price_rule_version'):
                    if key in p:public[key]=p[key]
                economy=p.get('workflow_mode')=='economy'
                brief=sales.brief(p,profile,brand) if economy else public
                # Product download has no dependency on the plan call.
                with ThreadPoolExecutor(max_workers=2) as prep:
                    reference=prep.submit(self.reference,p)
                    answer=self.api(job,'plan',prompts.PLAN_EMAIL if economy else prompts.PLAN_PROFILE,dict(brief,catalog=materials.context(self.store,profile)))
                    plan=profiles.normalize_plan(answer,profile)
                    if economy:p['prepared_email']=sales.compose(answer['email'],brief)
                    refs=[reference.result()]+materials.selected_images(plan,profile.get('material_manifest',self.config.get('material_manifest')))
                image=self.api(job,'image',prompts.IMAGE_PROFILE,dict(public,plan=plan),refs)
                raw=base64.b64decode(image['png_base64'],validate=True);validate_png(raw)
                p.update(plan=plan,concept_png=image['png_base64'],concept_sha256=hashlib.sha256(raw).hexdigest())
                self.store.advance(jid,'draft',p);return
            if stage=='draft':
                if p.get('prepared_email'):
                    identity=self.api(job,'identity',prompts.IDENTITY,{'facts':p['facts'][:6],'unit_count':p['product_reference']['unit_count']},[self.reference(p),(base64.b64decode(p['concept_png']),'image/png')])
                    if not all(identity.get(k) is True for k in ['correct_product','correct_count','usable_image']):raise ValueError('Factual product identity unresolved')
                    p['draft']=dict(p['prepared_email'],identity=identity);self.store.advance(jid,'send',p);return
                public={k:p[k] for k in ['company','facts','product_evidence_url','product_reference','plan']}
                public['sender']={'name':brand['name'],'signature':brand['signature']}
                profile=p.get('seller_profile') or profiles.resolve(self.config,brand)
                public['seller_profile']=profiles.public(profile)
                draft=self.api(job,'draft',prompts.DRAFT_PROFILE,public,[self.reference(p),(base64.b64decode(p['concept_png']),'image/png')])
                if not draft.get('subject') or len(draft['subject'])>150 or not draft.get('body') or len(draft['body'])>2400:raise ValueError('Concise subject and body required')
                if not all(draft.get('identity',{}).get(k) is True for k in ['correct_product','correct_count','usable_image']):raise ValueError('Factual product identity unresolved')
                draft['body']=sales.add_packaging_terms(draft['body'],p)
                p['draft']=draft;self.store.advance(jid,'send',p);return
            if stage=='send':
                result=mail.send(self.store,self.config,brand,job);p['delivery']=result
                self.store.advance(jid,'done',p,'done' if result['result'] in ('accepted','spooled') else 'blocked');return
            raise ValueError('Unknown stage')
        except RetryLater:self.store.fail(jid,'queued','Provider rate limited',60)
        except UncertainCall:
            self.store.fail(jid,'unknown','Remote outcome uncertain; reconcile recorded request ID')
            if job and job['stage']=='research':self.store.setting('discovery_next_at',time.time()+60)
        except Exception as e:
            self.store.fail(jid,'blocked',type(e).__name__+': '+str(e)[:250])
            if job and job['stage']=='research':self.store.setting('discovery_next_at',time.time()+60)
    def run(self,stop=None,until_idle=False):
        owner=uuid.uuid4().hex;self.store.acquire(owner);limits=dict(research=1,concept=2,draft=1,send=1);limits.update(self.config.get('concurrency',{}))
        if any(type(n) is not int or n<1 or n>8 for n in limits.values()):raise ValueError('Concurrency must be 1–8 per stage')
        active={};next_sync={}
        pool=ThreadPoolExecutor(max_workers=sum(limits.values())*len(self.brands)+len(self.brands))
        try:
            while not(stop and stop.is_set()):
                self.store.heartbeat(owner)
                for key,f in list(active.items()):
                    if f.done():
                        try:f.result()
                        except Exception:pass
                        del active[key]
                if self.store.setting('paused')=='false':
                    if self.config.get('auto_discover') and not until_idle:self.discover_next(active)
                    for bid,brand in self.brands.items():
                        if self.config.get('auto_send') and time.time()>=next_sync.get(bid,0) and (bid,'inbox',None) not in active:
                            active[(bid,'inbox',None)]=pool.submit(mail.sync,self.store,brand);next_sync[bid]=time.time()+60
                    for item in sorted(self.store.queue(),key=lambda x:{'send':0,'draft':1,'concept':2,'research':3}[x['stage']]):
                        key=(item['brand'],item['stage'],item['id'])
                        if key in active or sum(k[:2]==key[:2] for k in active)>=limits[item['stage']]:continue
                        active[key]=pool.submit(self.process,item['id'])
                self.store.setting('worker_status',json.dumps({'active':[{'brand':k[0],'stage':k[1],'job_id':k[2]} for k in active],'at':time.time()}))
                if until_idle and not active and not self.store.queue():break
                time.sleep(.25)
        finally:
            # Complete active operations and keep heartbeat while draining. Never cancel SMTP mid-DATA.
            while any(not f.done() for f in active.values()):self.store.heartbeat(owner);time.sleep(.5)
            pool.shutdown(wait=True);self.store.release(owner)
    def discover_next(self,active):
        """One discovery reservoir across accounts; round-robin allocation is persistent."""
        if any(k[1]=='research' for k in active):return
        with self.store.db() as c:
            pending=[dict(r) for r in c.execute("SELECT brand,stage FROM jobs WHERE state IN ('queued','running')")]
        if any(r['stage']=='research' for r in pending):return
        if time.time()<float(self.store.setting('discovery_next_at') or 0):return
        brands=list(self.brands);turn=int(self.store.setting('discovery_turn') or 0)
        maximum=self.config.get('performance',{}).get('max_pending_per_brand',4)
        for offset in range(len(brands)):
            idx=(turn+offset)%len(brands);bid=brands[idx]
            if sum(r['brand']==bid for r in pending)>=maximum:continue
            self.store.add(bid,{},'research')
            self.store.setting('discovery_turn',idx+1)
            self.store.setting('discovery_next_at',time.time()+2)
            return
