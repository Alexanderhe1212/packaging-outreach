"""Keep catalog/search platforms out of exhibitor website and email counts."""
from urllib.parse import urlsplit
PLATFORMS=('flipsnack.com','issuu.com','linkedin.com','facebook.com','instagram.com','youtube.com','mapyourshow.com','a2zinc.net')
def company_website(url):
 try:
  p=urlsplit(url);host=(p.hostname or '').lower()
  return bool(p.scheme in ('https','http') and host and not p.username and not p.password and not any(host==d or host.endswith('.'+d) for d in PLATFORMS))
 except ValueError:return False

def observed_contacts(item):
 mails=set();people=set()
 if item.get('website') and not company_website(item['website']):return mails,people
 for result in item.get('results',[]):
  report=result.get('report',{})
  if not company_website(item.get('website') or report.get('website','')):continue
  for value in report.get('emails',[]):
   address=value.get('email','') if isinstance(value,dict) else value
   if isinstance(address,str) and '@' in address:mails.add(address.casefold())
  for person in report.get('qualified_people',[]):
   if person.get('name') and person.get('email'):
    mails.add(person['email'].casefold());people.add((person['name'].casefold(),person['email'].casefold()))
 return mails,people
