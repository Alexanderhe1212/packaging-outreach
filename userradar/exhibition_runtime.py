"""Constant-time progress snapshots and bounded retries for read-only local queries."""
import json
import threading
import time
import urllib.error
import urllib.request
from exhibition_contacts import observed_contacts

class ProgressTotals:
    def __init__(self, records=()):
        self.lock=threading.RLock()
        self.ids=set();self.emails=set();self.people=set();self.provisional=set()
        self.blocked=0;self.companies=0;self.observations=0
        for record in records:self.add(record)

    def add(self, item):
        with self.lock:
            identifier=item['record_id']
            if identifier in self.ids:return
            emails,people=observed_contacts(item)
            self.ids.add(identifier);self.emails.update(emails);self.people.update(people)
            self.blocked+=bool(item.get('retrieval_incomplete'))
            self.companies+=bool(emails)
            for candidate in item.get('public_search',{}).get('companies',[]):
                if candidate.get('name') and candidate.get('email'):
                    self.provisional.add((candidate['name'].casefold(),candidate['email'].casefold()))
            self.observations+=sum(len(result.get('report',{}).get('people',[])) for result in item.get('results',[]))

    def snapshot(self):
        with self.lock:
            return dict(completed=len(self.ids),attempted=len(self.ids),retrieval_incomplete=self.blocked,
                        companies_with_email=self.companies,public_source_name_email_candidates=len(self.provisional),
                        named_email_pairs=len(self.people),observed_unique_emails=len(self.emails),person_observations=self.observations)

def api(path, data=None):
    request=urllib.request.Request('http://127.0.0.1:18830'+path,
        data=None if data is None else json.dumps(data).encode(),
        headers={'Content-Type':'application/json','Origin':'http://127.0.0.1:18830'})
    # Only observation GETs may be repeated; a POST may already have created work.
    attempts=3 if data is None else 1
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request,timeout=25) as response:return json.load(response)
        except (urllib.error.URLError,TimeoutError,ConnectionError) as error:
            if isinstance(error,urllib.error.HTTPError) and error.code not in (500,502,503,504):raise
            if attempt+1==attempts:raise
            time.sleep(.2*(2**attempt))

# A legal suffix is formatting, not permission to substitute a different brand.
def resolved_website(row, found):
    import re
    from urllib.parse import urlsplit
    from exhibition_contacts import company_website
    def compact(value):return re.sub(r'[^a-z0-9]','',value.lower())
    def legal_core(value):
        value=value.lower().replace('&',' and ').strip()
        previous=None
        while previous!=value:
            previous=value
            value=re.sub(r'[\s,.]+(?:llc|incorporated|inc|limited|ltd|corporation|corp|gmbh|plc|llp)[\s,.]*$','',value)
        return re.findall(r'[a-z0-9]+',value)
    names=[row['company']]+row.get('aliases',[])
    exact={compact(name) for name in names if compact(name)}
    for candidate in found.get('companies',[])[:1]:
        site=candidate.get('website','')
        if not company_website(site):continue
        sources=[source for source in candidate.get('sources',[]) if source.get('quote') and source.get('url','').startswith(('https://','http://'))]
        if not sources:continue
        if compact(candidate.get('company','')) in exact:return site
        words=legal_core(candidate.get('company',''))
        if len(''.join(words))<8:continue
        for name in names:
            if words!=legal_core(name):continue
            pattern=r'\b'+r'[\W_]+'.join(re.escape(word) for word in words)+r'\b'
            site_host=(urlsplit(site).hostname or '').removeprefix('www.')
            if any((urlsplit(source['url']).hostname or '').removeprefix('www.')==site_host
                   and re.search(pattern,source['quote'].lower().replace('&',' and ')) for source in sources):
                return site
    return ''
