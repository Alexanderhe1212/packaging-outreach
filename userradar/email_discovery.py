"""Bounded official-page discovery. Search snippets never become contacts."""
import json,re,urllib.request,urllib.error
from urllib.parse import urlsplit,urlunsplit,urlencode
from bs4 import BeautifulSoup
from contact_routes import _safe_url

INTEREST=re.compile(r'contact|customer.?care|customer.?service|support|help|wholesale|distributor|stockist|trade|faq|impressum|kontakt',re.I)
def priority(url):
 path=urlsplit(url).path
 return (0 if re.search(r'contact|customer|support|help',path,re.I) else 1,len(path))

def page_routes(raw,start):
 found=[]
 for a in BeautifulSoup(raw,'html.parser').select('a[href]'):
  url=_safe_url(a['href'],start)
  if url and INTEREST.search(a.get_text(' ',strip=True)+' '+urlsplit(url).path):found.append(url)
 return sorted(set(found),key=priority)[:6]

def sitemap_links(raw,start):
 from trafilatura.sitemaps import SitemapObject
 obj=SitemapObject(start,urlsplit(start).hostname,[])
 obj.content=raw;obj.extract_sitemap_links()
 return obj.urls,obj.sitemap_urls

def sitemap_routes(raw,start):
 urls,_=sitemap_links(raw,start)
 return sorted({u for value in urls if (u:=_safe_url(value,start)) and INTEREST.search(urlsplit(u).path)},key=priority)[:6]

def read_sitemap(url,start,robot):
 from app import public_url,host,Redirects,AGENT
 from browser_transport import budget_remaining,check_budget
 from rate_limits import check,observe
 public_url(url);check(url)
 if host(url)!=host(start) or not robot.can_fetch(AGENT,url):return ''
 request=urllib.request.Request(url,headers={'User-Agent':AGENT,'Accept':'application/xml,text/xml,text/plain'})
 try:
  with urllib.request.build_opener(Redirects(host(start))).open(request,timeout=budget_remaining(3)) as response:
   raw=response.read(2_000_001);check_budget()
   if len(raw)>2_000_000:raise ValueError('Sitemap exceeds size limit')
   return raw.decode('utf-8',errors='replace')
 except urllib.error.HTTPError as e:
  if e.code==429:
   from rate_limits import parse_retry_after
   delay=parse_retry_after(e.headers.get('Retry-After','60'))
   raise observe(url,delay if delay is not None else 60,e.headers.get('Server',''))
  raise

def discover_sitemap(start,robot):
 from request_budget import request_scope
 p=urlsplit(start);root=urlunsplit((p.scheme,p.netloc,'/sitemap.xml','',''))
 todo=list(robot.site_maps() or [])+[root];seen=set();found=[]
 with request_scope(seconds=5):
  while todo and len(seen)<2:
   url=todo.pop(0)
   if url in seen:continue
   seen.add(url)
   raw=read_sitemap(url,start,robot)
   found.extend(sitemap_routes(raw,start))
   _,children=sitemap_links(raw,start)
   # Shopify product/collection maps do not help contact discovery.
   todo=sorted([u for u in children if 'page' in u or 'post' in u],key=lambda u:('page' not in u,len(u)))+todo
   if found:break
 return list(dict.fromkeys(found))[:4]

def search_json(query):
 from browser_transport import budget_remaining,check_budget
 # Fixed loopback service; target websites cannot choose an internal endpoint.
 url='http://127.0.0.1:18831/search?'+urlencode({'q':query,'format':'json','categories':'general'})
 request=urllib.request.Request(url,headers={'Accept':'application/json'})
 with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=budget_remaining(9)) as r:
  raw=r.read(2_000_001);check_budget()
  if len(raw)>2_000_000:raise ValueError('Search response too large')
  return json.loads(raw)

def search_routes(start):
 domain=urlsplit(start).hostname.removeprefix('www.')
 from browser_transport import LOCAL
 LOCAL.search_diagnostics={}
 payload=search_json('site:'+domain+' contact email customer service')
 LOCAL.search_diagnostics={'unresponsive_engines':payload.get('unresponsive_engines',[]),'returned_results':len(payload.get('results',[]))}
 found=[]
 for item in payload.get('results',[])[:20]:
  url=_safe_url(item.get('url',''),start)
  if url and url not in found:found.append(url)
 return sorted(found,key=priority)[:3]
