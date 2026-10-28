"""Independent, bounded public document reads for evidence-based enrichment."""
import copy,hashlib,json,re,time,urllib.request,urllib.error,urllib.parse,urllib.robotparser
import subprocess,tempfile,threading
from pathlib import Path
from bs4 import BeautifulSoup
from contact_extract import prepare_visible_contacts,NAME
from contact_quality import country_hint,whatsapp_links
BUNDLED_PYTHON='python'
MAX_PDF_BYTES=25_000_000
BROKERS=('rocketreach.co','signalhire.com','contactout.com','lusha.com','zoominfo.com','leadiq.com','seamless.ai','apollo.io','hunter.io')

# These are structural boundaries, not a broader decision-maker role policy.
_TITLE_LINE=re.compile(r'\b(director|manager|chief|founder|owner|president|officer|consultant|sales|marketing|exports?|procurement|international|department|coordinator)\b',re.I)
_CONTACT_BOUNDARY=re.compile(r'^(?:(?:matchmaking|general|customer|company|office|administration|media|press)\s+(?:contact|service|support)|contact(?: information| details)?|for more information please contact)\s*:?',re.I)

def person_blocks(text):
    """Split visible person/department boundaries, never join adjacent people."""
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    chunks=[];current=[]
    for line in lines:
        bare=re.sub(r'^(?:Mr|Ms|Mrs|Dr)\.?\s+', '',line,flags=re.I)
        name_like=bool(NAME.fullmatch(bare) or (bare.isupper() and NAME.fullmatch(bare.title())))
        inline_name=re.match(r"^([A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'.-]+(?: [A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'.-]+){1,3})\s+(.+)$",bare)
        inline_person=bool(inline_name and not _TITLE_LINE.search(inline_name[1]) and _TITLE_LINE.search(inline_name[2]))
        boundary=_CONTACT_BOUNDARY.match(line) or inline_person or (name_like and not _TITLE_LINE.search(bare))
        if boundary and current:
            chunks.append('\n'.join(current));current=[]
        current.append(line)
    if current:chunks.append('\n'.join(current))
    return [part for part in chunks if 5<=len(part)<=1400]

def publication(soup,url,text=''):
    """Publication time stays distinct from fetch time; do not date by copyright."""
    values=[]
    for tag in soup.select('meta[property="article:published_time"],meta[name="date"],meta[itemprop="datePublished"],time[datetime]'):
        values.append(tag.get('content') or tag.get('datetime') or '')
    values.extend(re.findall(r'\b(?:19|20)\d{2}-\d{2}-\d{2}\b',text[:1500]))
    for value in values:
        match=re.search(r'\b((?:19|20)\d{2}-\d{2}-\d{2})\b',value)
        if match:return {'published_date':match[1],'source_year':int(match[1][:4]),'date_basis':'published_page_date'}
    # A dated event URL is weaker than a publication date, but must not be lost.
    match=re.search(r'(?:^|[/_-])((?:19|20)\d{2})(?:[/_.-]|$)',urllib.parse.urlsplit(url).path)
    if match:return {'source_year':int(match[1]),'date_basis':'year_in_source_url'}
    return {}

def layout_columns(text):
    """Keep fixed-width PDF columns apart before building person scopes."""
    rows=[];starts={}
    for line in text.splitlines():
        segments=[(m.start(),m.group().strip()) for m in re.finditer(r'\S(?:.*?\S)?(?= {4,}|$)',line)]
        rows.append(segments)
        for start,value in segments:
            if start>=20:starts[start]=starts.get(start,0)+1
    clusters=[]
    for start,count in sorted(starts.items()):
        if clusters and start-clusters[-1][0]<=6:clusters[-1][1]+=count
        else:clusters.append([start,count])
    anchors=[0]+[start for start,count in clusters if count>=3]
    columns={anchor:[] for anchor in anchors}
    for segments in rows:
        row={anchor:[] for anchor in anchors}
        for start,value in segments:
            anchor=max(a for a in anchors if a<=start+6)
            row[anchor].append(value)
        for anchor in anchors:columns[anchor].append(' '.join(row[anchor]))
    return ['\n'.join(lines) for lines in columns.values() if any(lines)]

def pdf_document(pages,url):
    """Read at most 40 layout-preserving pages; retain provenance per block."""
    import html
    selected=pages[:40]
    raw=''.join('<section>'+html.escape(page).replace('\n','<br>')+'</section>' for page in selected)
    data=document(raw,url,'pdf');contexts=[]
    for index,page in enumerate(selected):
        for column in layout_columns(page):
            # PDF glyph kerning can introduce spaces inside an address. Only
            # collapse one standalone email field, retaining the literal text.
            # No names/domains are synthesized and adjacent rows never join.
            from app import EMAIL
            normalized=[]
            for line in column.splitlines():
                compact=re.sub(r'\s+','',line)
                normalized.append(compact if '@' in line and EMAIL.fullmatch(compact) else line)
            for block in person_blocks('\n'.join(normalized)):
                contexts.append({'text':block,'page':index+1})
    data['blocks']=list(dict.fromkeys(item['text'] for item in contexts))
    data['block_contexts']=contexts;data['page_limit']=40
    data['pdf_email_normalization']='独立PDF邮箱字段的字距空格归一；原始布局另存HTML与PDF，不跨行合成地址'
    data['pages_read']=len(selected)
    # Do not build WhatsApp ownership scopes from flattened PDF columns.
    data['whatsapp_scopes']=[]
    years=set(re.findall(r'\b(?:19|20)\d{2}\b','\n'.join(selected[:1])[:1800]))
    if len(years)==1:
        data.update(source_year=int(next(iter(years))),date_basis='year_on_document_cover')
    return data,raw

def acceptable_url(url):
    p=urllib.parse.urlsplit(url)
    return p.scheme in ('http','https') and bool(p.hostname) and not p.username and not p.password and p.port in (None,80,443) and not any(p.hostname==d or p.hostname.endswith('.'+d) for d in BROKERS)

def document(raw,url,content_type='html'):
    soup=BeautifulSoup(raw,'html.parser')
    region=country_hint(soup)
    from whatsapp_attribution import publication_scopes
    prepare_visible_contacts(soup)
    wa_scopes=publication_scopes(soup,url,region)
    for tag in soup(['script','style','noscript','svg','form']):tag.decompose()
    prepare_visible_contacts(soup)
    # Alt text is published content, but never treated as a contact channel.
    for img in soup.select('img[alt]'):
        if img['alt']:img.replace_with(' '+img['alt']+' ')
    text=soup.get_text(' ',strip=True)
    links=[a['href'] for a in soup.select('a[href]')]
    # Preserve actual anchor semantics for employer-domain affiliation checks.
    # A client/supplier backlink is not an official regional-site declaration.
    link_contexts=[]
    for anchor in soup.select('a[href]'):
        label=anchor.get_text(' ',strip=True);scope=label
        parent=anchor.parent
        for depth in range(3):
            if parent is None:break
            scoped_text=parent.get_text(' ',strip=True)
            if len(scoped_text)>600:break
            scope=scoped_text
            parent=parent.parent
        link_contexts.append({'url':anchor['href'],'label':label,'text':scope})
    entity_headings=[h.get_text(' ',strip=True) for h in soup.select('h1,h2,title') if len(h.get_text(' ',strip=True))<=200]
    from app import emails as extract_emails
    email_contexts=[]
    for tag in soup.find_all(['p','li','address','td','a']):
        value=tag.get_text(' ',strip=True)
        addresses=extract_emails(value)
        if not addresses:continue
        scope=value;parent=tag.parent
        for depth in range(3):
            if parent is None:break
            scoped_text=parent.get_text(' ',strip=True)
            if len(scoped_text)>600:break
            scope=scoped_text;parent=parent.parent
        email_contexts.append({'emails':addresses,'text':scope})
    published_whatsapp=whatsapp_links(soup,url)
    # Retain company-level page facts, but do not let an outer container attach
    # footer/navigation contacts to a person card nested beside them.
    for tag in soup(['footer','nav','aside']):tag.decompose()
    blocks=[]
    for tag in soup.find_all(['p','li','address','td','div','article','section','blockquote','figcaption']):
        value=tag.get_text('\n',strip=True)
        names={h.get_text(' ',strip=True) for h in tag.find_all(['h1','h2','h3','h4']) if NAME.fullmatch(h.get_text(' ',strip=True))}
        if len(names)>1:continue
        for part in person_blocks(value):
            if part not in blocks:blocks.append(part)
    data={'url':url,'text':text,'blocks':blocks,'links':links,'whatsapp':published_whatsapp,'whatsapp_scopes':wa_scopes,'country_hint':region,'checked_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'content_type':content_type}
    data['link_contexts']=link_contexts;data['entity_headings']=entity_headings;data['email_contexts']=email_contexts
    data.update(publication(soup,url,text))
    from harvester_bridge import email_hints
    data['harvester']={}
    data['email_hints']=email_hints(raw,url,diagnostics=data['harvester'])
    from website_email_bridge import email_hints as website_email_hints
    data['email_hints'].extend(website_email_hints(raw,url))
    data['email_decodings']=soup.__dict__.get('_ur_email_decodings',[])
    if content_type=='html':
        # Parser evidence is derived from this independently read page, never
        # from candidate/source quotes. PDF column scopes follow a separate path.
        from app import extract
        data['people']=extract(raw,url)[0]
        # Preserve the original Person field record so independent verification
        # can use Microdata/JSON-LD without flattening company contact points.
        structured=[p['evidence'] for p in data['people'] if p.get('structured_record')]
        data['blocks']=list(dict.fromkeys(data['blocks']+structured))
        from structured_contacts import person_whatsapp_scopes
        data['whatsapp_scopes'].extend(person_whatsapp_scopes(data['people'],url))
    return data


def download_route(url):
    """Recognize document handlers, not an identity or an email hint."""
    parts=urllib.parse.urlsplit(url)
    keys={k.lower() for k in urllib.parse.parse_qs(parts.query,keep_blank_values=True)}
    return bool(keys & {'download_file','attachment_id','download'}) or bool(re.search(r'(?:^|/)download(?:[./-]|$)',parts.path,re.I))

def read_download(url,domain):
    """Read one robots-approved original with the same redirect/public-IP guard.

    A download filename or MIME type alone never establishes a PDF. Its bytes
    must carry the PDF signature; HTML handlers retain their original URL.
    """
    from app import AGENT,Redirects
    from browser_transport import budget_remaining,check_budget
    check_budget()
    req=urllib.request.Request(url,headers={'User-Agent':AGENT})
    with urllib.request.build_opener(Redirects(domain)).open(req,timeout=budget_remaining(15)) as response:
        prefix=response.read(1024);check_budget()
        is_pdf=prefix.startswith(b'%PDF')
        mime=response.headers.get_content_type()
        is_html=mime in ('text/html','application/xhtml+xml') or bool(re.match(br'\s*(?:<!doctype\s+html|<html\b)',prefix,re.I))
        if not is_pdf and not is_html:raise ValueError('下载来源不是有效 PDF 或网页；未采用二进制内容')
        cap=MAX_PDF_BYTES if is_pdf else 2_000_000
        body=bytearray(prefix)
        while len(body)<=cap:
            check_budget()
            chunk=response.read(min(65536,cap+1-len(body)))
            if not chunk:break
            body.extend(chunk)
        check_budget()
        if len(body)>cap:raise ValueError('PDF 或网页超过本轮大小上限')
        if is_pdf:return bytes(body),None
        charset=response.headers.get_content_charset() or 'utf-8'
        return None,bytes(body).decode(charset,errors='replace')

def source_failure(error):
    """Retain bounded operational HTTP fields, never response bodies/credentials."""
    from rate_limits import parse_retry_after
    attrs=vars(error)
    data={key:attrs[key] for key in ('http_status','retry_after_seconds','remaining_retry_seconds',
          'retry_at','rate_limit_cache_hit','response_server') if key in attrs}
    status=attrs.get('http_status',attrs.get('code'))
    if isinstance(status,int):data['http_status']=status
    headers=getattr(error,'headers',None)
    if headers:
        retry=headers.get('Retry-After')
        if retry is not None:
            data['retry_after_header']=str(retry)[:120]
            seconds=parse_retry_after(str(retry))
            if seconds is not None:data.setdefault('retry_after_seconds',seconds)
        server=headers.get('Server')
        if server:data.setdefault('response_server',str(server)[:80])
    return data


def raise_source_failure(data):
    error=ValueError(data['error'])
    for key,value in data.get('error_metadata',{}).items():setattr(error,key,value)
    raise error


class SourceReader:
    def __init__(self,folder=None,cancel=None):
        self.folder=Path(folder) if folder else None
        if self.folder:self.folder.mkdir(parents=True,exist_ok=True)
        self.cache={};self.robots={};self.transports={};self.cancel=cancel or threading.Event();self.deadline=time.monotonic()+210
        self._reused_sources={}
        self.read_metrics={"network_reads":0,"cache_hits":0,"reused_reads":0}
    def fork(self,folder=None,cancel=None):
        """Reuse successful originals only within this job, without changing dates.

        A fresh top-level reader has no inherited evidence. Verification still
        runs independently for every identity; no decisions are cached. Failed
        reads are retried, and the child gets its own bounded read budget.
        """
        child=SourceReader(folder=folder,cancel=cancel or self.cancel)
        child._reused_sources=copy.deepcopy({u:d for u,d in {**self._reused_sources,**self.cache}.items() if "error" not in d})
        child.robots=dict(self.robots)
        child.transports=copy.deepcopy(self.transports)
        return child
    def read(self,url):
        from request_budget import request_scope
        with request_scope(deadline=self.deadline,cancel=self.cancel):
            return self._read(url)
    def _read(self,url):
        from app import public_url,host,Redirects,AGENT,fetch
        from browser_transport import reset_budget,LOCAL,budget_remaining,check_budget
        if self.cancel.is_set():raise ValueError('查询已停止')
        if not acceptable_url(url):raise ValueError('仅支持公开业务来源；未使用联系人数据经纪站点')
        if url in self.cache:
            self.read_metrics['cache_hits']+=1
            data=self.cache[url]
            if 'error' in data:raise_source_failure(data)
            return data
        if len(self.cache)>=8 or time.monotonic()>self.deadline:raise ValueError('本轮来源核对达到时间或数量上限，保留未完成项')
        if url in self._reused_sources:
            data=copy.deepcopy(self._reused_sources[url]);self.cache[url]=data
            self.read_metrics['reused_reads']+=1
            if self.folder:
                key=hashlib.sha256(url.encode()).hexdigest()[:20]
                (self.folder/(key+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2))
            return data
        from rate_limits import check as check_cooldown
        check_cooldown(url)
        domain=host(url);parts=urllib.parse.urlsplit(url);reset_budget()
        origin=parts.scheme+'://'+parts.netloc
        for key,value in self.transports.get(origin,{}).items():setattr(LOCAL,key,value)
        raw=None;pdf_body=None;geometry=[];geometry_error=''
        try:
            public_url(url)
            if origin not in self.robots:
                from robots_rules import read_robots
                robot,robots_status=read_robots(origin,domain,fetch)
                self.robots[origin]=robot
            if not self.robots[origin].can_fetch(AGENT,url):raise ValueError('来源网站不允许自动读取；保留为搜索线索')
            if self.cancel.is_set():raise ValueError('查询已停止')
            self.read_metrics['network_reads']+=1
            explicit_pdf=parts.path.lower().endswith('.pdf')
            if explicit_pdf or download_route(url):
                pdf_body,raw=read_download(url,domain)
                if explicit_pdf and pdf_body is None:raise ValueError('PDF 无效；原地址未返回 PDF 文件')
            else:
                try:raw=fetch(url,domain)
                except ValueError as exc:
                    # Exactly one MIME fallback, never retry access restrictions,
                    # rate limits, denied robots, or other network failures.
                    if str(exc)!='不是可读取的网页。':raise
                    pdf_body,raw=read_download(url,domain)
            if pdf_body is not None:
                body=pdf_body
                with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
                    tmp.write(body);tmp.flush()
                    code='import sys,json;from pypdf import PdfReader;r=PdfReader(sys.argv[1]);print(json.dumps([p.extract_text(extraction_mode="layout") or "" for p in r.pages[:40]]))'
                    proc=subprocess.run([BUNDLED_PYTHON,'-c',code,tmp.name],capture_output=True,text=True,timeout=budget_remaining(20))
                    if proc.returncode:raise ValueError('公开 PDF 文本读取失败')
                    pages=json.loads(proc.stdout)
                    selected=[i+1 for i,text in enumerate(pages) if re.search(r'whats\s*app',text,re.I)]
                    if selected:
                        try:
                            geometry_code='import sys,json;sys.path.insert(0,sys.argv[2]);from pdf_channel_scopes import extract_pdf_geometry;print(json.dumps(extract_pdf_geometry(sys.argv[1],json.loads(sys.argv[3]))))'
                            geo=subprocess.run([BUNDLED_PYTHON,'-c',geometry_code,tmp.name,str(Path(__file__).resolve().parent),json.dumps(selected)],capture_output=True,text=True,timeout=budget_remaining(30))
                            if geo.returncode:raise ValueError('geometry unavailable')
                            geometry=json.loads(geo.stdout)
                        except (ValueError,subprocess.SubprocessError):
                            geometry_error='PDF按钮位置未能读取；原文身份与邮箱核验仍保留'
                data,raw=pdf_document(pages,url)
                if geometry:
                    from pdf_channel_scopes import pdf_whatsapp_scopes
                    data['pdf_geometry']=geometry
                    data['whatsapp_scopes']=pdf_whatsapp_scopes(geometry,url)
                if geometry_error:data['pdf_channel_error']=geometry_error
            else:
                data=document(raw,url)
            self.cache[url]=data
        except Exception as e:
            data={'url':url,'error':str(e)[:250],'error_metadata':source_failure(e)};self.cache[url]=data
        self.transports[origin]={key:getattr(LOCAL,key,False) for key in ('count','browser_mode','blocked')}
        if self.folder:
            key=hashlib.sha256(url.encode()).hexdigest()[:20]
            if pdf_body is not None:(self.folder/(key+'.pdf')).write_bytes(pdf_body)
            if raw is not None:(self.folder/(key+'.html')).write_text(raw)
            (self.folder/(key+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2))
        if 'error' in data:raise_source_failure(data)
        return data
