"""One bounded rendered page. Robots and public DNS are checked by the caller."""
import asyncio,contextlib,json,sys
from urllib.parse import urlsplit
async def capture(data):
 from crawl4ai import AsyncWebCrawler,BrowserConfig,CrawlerRunConfig,CacheMode
 url=data['url'];target=urlsplit(url);domain=(target.hostname or '').removeprefix('www.')
 state={}
 async def created(page,context,**kwargs):
  async def route_request(route):
   req=route.request;p=urlsplit(req.url)
   if p.scheme not in ('http','https') or (p.hostname or '').removeprefix('www.')!=domain or p.username or p.password or p.port not in (None,80,443,target.port) or req.method not in ('GET','HEAD') or req.resource_type in ('image','media','font'):
    return await route.abort()
   return await route.continue_()
  await context.route('**/*',route_request)
  return page
 async def final(page,**kwargs):
  state['url']=page.url;state['title']=await page.title();return page
 config=BrowserConfig(browser_type='chromium',chrome_channel='chrome',headless=True,use_managed_browser=False,use_persistent_context=False,enable_stealth=False,ignore_https_errors=False,verbose=False)
 run=CrawlerRunConfig(wait_until='domcontentloaded',page_timeout=min(18000,data['timeout_ms']),delay_before_return_html=.5,cache_mode=CacheMode.BYPASS,check_robots_txt=False,prefetch=True,simulate_user=False,override_navigator=False,magic=False,verbose=False)
 async with AsyncWebCrawler(config=config) as crawler:
  crawler.crawler_strategy.set_hook('on_page_context_created',created)
  crawler.crawler_strategy.set_hook('before_return_html',final)
  r=await crawler.arun(url=url,config=run)
  status=r.redirected_status_code if r.redirected_status_code is not None else r.status_code
  html=r.html or ''
  if len(html.encode())>2000000:raise ValueError('Page too large')
  return {'success':r.success,'status':status,'url':state.get('url') or r.redirected_url or r.url,'title':state.get('title',''),'html':html,'error':r.error_message,'retry_after':(r.response_headers or {}).get('retry-after','')}
if __name__=='__main__':
 data=json.loads(sys.stdin.read())
 with contextlib.redirect_stdout(sys.stderr):result=asyncio.run(capture(data))
 print(json.dumps(result))
