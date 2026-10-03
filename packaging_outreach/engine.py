"""Resumable stages with concurrent independent customers and one sender per brand."""
import base64,hashlib,json,time,uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from . import sources,materials,prompts,mail
from .providers import HTTPProvider,RetryLater,UncertainCall
from .images import validate_png
from .store import Store

class Engine:
    def __init__(self,config,provider=None,fetcher=None):
        self.config=config;self.store=Store(config['workspace']);self.provider=provider or HTTPProvider(config)
        self.fetcher=fetcher or sources.fetch_public;self.brands={b['id']:b for b in config['brands']}
    def api(self,job,stage,prompt,data,images=()):
        return self.store.cached_call(job['id'],stage,lambda rid:self.provider.call(stage,prompt,data,rid,images))
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
    def verify(self,candidate,pages):
        urls=list(dict.fromkeys(candidate[k] for k in ('company_url','email_source_url','product_evidence_url')));allowed={sources.host(candidate['company_url'])}
        browser=self.config.get('source_mode')=='browser_excerpts'
        if browser:
            collected={p['url']:{'url':p['url'],'text':p['text'],'sha256':hashlib.sha256(p['text'].encode()).hexdigest(),'checked_at':sources.NOW().isoformat(),'provenance':'official_subscription_browser_excerpt'} for p in pages if len(p['text'].split())<=200}
        else:
            with ThreadPoolExecutor(max_workers=3) as pool:collected=dict(zip(urls,pool.map(lambda u:self.fetcher(u,allowed),urls)))
        result=sources.verify_candidate(candidate,{'constraints':{}},lambda url,hosts:collected[url],allow_browser=browser)
        product=collected[candidate['product_evidence_url']];image=candidate['product_image_url'];count=candidate['unit_count'];quote=candidate['count_evidence_quote']
        if image not in product.get('images',[]) and image not in product['text']:raise ValueError('Product image URL not bound to source page')
        if type(count) is not int or not 1<=count<=50 or not quote or sources.normalize(quote) not in sources.normalize(product['text']):raise ValueError('Product quantity needs source evidence')
        p=result['payload'];p.update(company=result['company'],recipient=result['recipient'],product_reference={'url':image,'source_url':p['product_evidence_url'],'unit_count':count,'count_evidence_quote':quote},source_mode=self.config.get('source_mode','direct_https'))
        return p
    def process(self,jid):
        if not self.store.claim(jid):return
        job=self.store.get(jid);p=job['payload'];brand=self.brands[job['brand']]
        try:
            stage=job['stage']
            if stage=='research':
                with self.store.db() as c:excluded=[r[0] for r in c.execute("SELECT DISTINCT company_key FROM jobs WHERE company_key!=''")]
                result=self.api(job,'research',prompts.RESEARCH,{'target':self.config['target'],'excluded_company_domains':excluded})
                candidate=result.get('candidate')
                if candidate:
                    verified=self.verify(candidate,result.get('pages',[]));self.store.add(job['brand'],verified,'concept')
                self.store.advance(jid,'done',{'candidate_found':bool(candidate)},'done');return
            if stage=='concept':
                public={k:p[k] for k in ['company','facts','product_evidence_url','product_reference']}
                plan=self.api(job,'plan',prompts.PLAN,dict(public,catalog=materials.context(self.store)))
                for option in ['a','b']:
                    o=plan[option]
                    if o['box'] not in materials.BOXES or o['insert'] not in materials.INSERTS or len(o['accessories'])>2 or any(x not in materials.ACCESSORIES for x in o['accessories']):raise ValueError('Unknown material selection')
                if plan['a']['box']==plan['b']['box']:raise ValueError('A and B require distinct structures')
                refs=[self.reference(p)]+materials.selected_images(plan,self.config.get('material_manifest'))
                image=self.api(job,'image',prompts.IMAGE,dict(public,plan=plan),refs)
                raw=base64.b64decode(image['png_base64'],validate=True);validate_png(raw)
                p.update(plan=plan,concept_png=image['png_base64'],concept_sha256=hashlib.sha256(raw).hexdigest())
                self.store.advance(jid,'draft',p);return
            if stage=='draft':
                public={k:p[k] for k in ['company','facts','product_evidence_url','product_reference','plan']}
                public['sender']={'name':brand['name'],'signature':brand['signature']}
                draft=self.api(job,'draft',prompts.DRAFT,public,[self.reference(p),(base64.b64decode(p['concept_png']),'image/png')])
                if not draft.get('subject') or len(draft['subject'])>150 or not draft.get('body') or len(draft['body'])>2400:raise ValueError('Concise subject and body required')
                if not all(draft.get('identity',{}).get(k) is True for k in ['correct_product','correct_count','usable_image']):raise ValueError('Factual product identity unresolved')
                p['draft']=draft;self.store.advance(jid,'send',p);return
            if stage=='send':
                result=mail.send(self.store,self.config,brand,job);p['delivery']=result
                self.store.advance(jid,'done',p,'done' if result['result'] in ('accepted','spooled') else 'blocked');return
            raise ValueError('Unknown stage')
        except RetryLater:self.store.fail(jid,'queued','Provider rate limited',60)
        except UncertainCall:self.store.fail(jid,'unknown','Remote outcome uncertain; reconcile recorded request ID')
        except Exception as e:self.store.fail(jid,'blocked',type(e).__name__+': '+str(e)[:250])
    def run(self,stop=None,until_idle=False):
        owner=uuid.uuid4().hex;self.store.acquire(owner);limits=dict(research=1,concept=2,draft=1,send=1);limits.update(self.config.get('concurrency',{}))
        if any(type(n) is not int or n<1 or n>8 for n in limits.values()):raise ValueError('Concurrency must be 1–8 per stage')
        active={};next_discovery={};next_sync={}
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
                    queue=self.store.queue()
                    for bid,brand in self.brands.items():
                        if self.config.get('auto_discover') and not until_idle and time.time()>=next_discovery.get(bid,0):
                            pending=[x for x in queue if x['brand']==bid and x['stage'] in ('research','concept','draft')]
                            if len(pending)<6 and not any(k[0]==bid and k[1]=='research' for k in active) and not any(x['stage']=='research' for x in pending):
                                self.store.add(bid,{},'research');next_discovery[bid]=time.time()+30
                        if self.config.get('auto_send') and time.time()>=next_sync.get(bid,0) and (bid,'inbox',None) not in active:
                            active[(bid,'inbox',None)]=pool.submit(mail.sync,self.store,brand);next_sync[bid]=time.time()+60
                    for item in sorted(self.store.queue(),key=lambda x:0 if x['stage']=='send' else 1):
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
