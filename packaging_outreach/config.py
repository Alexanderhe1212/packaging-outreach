"""A single portable JSON config. Secrets are environment references only."""
import json,os,re
from pathlib import Path
from urllib.parse import urlsplit


def load(path):
    path=Path(path).resolve();c=json.loads(path.read_text());c['_config_path']=str(path)
    c['workspace']=str((path.parent/Path(c.get('workspace','runtime'))).resolve())
    api=c.get('api',{})
    if any(k in api for k in ('api_key','password','token')):raise ValueError('Use api_key_env, never literal secrets')
    if api:
        shared={'base_url':api['base_url'],'api_key_env':api.get('api_key_env','OUTREACH_API_KEY')}
        defaults={'research':dict(shared,kind='responses',model=api['text_model'],web_search=True),'text':dict(shared,kind='chat',model=api['text_model']),'image':dict(shared,kind='image_edits',model=api['image_model'])}
        defaults.update(c.get('providers',{}));c['providers']=defaults
    brands=c.get('brands',[])
    if not brands or len({b['id'] for b in brands})!=len(brands):raise ValueError('Unique brand profiles required')
    for b in brands:
        if any(k in b for k in ('password','api_key','token')):raise ValueError('Use password_env for mailbox secrets')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}',b['id']):raise ValueError('Invalid brand ID')
        if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',b['sender']):raise ValueError('Valid sender required')
        if not re.fullmatch(r'[0-9]{7,15}',b['whatsapp']):raise ValueError('WhatsApp needs international digits only')
    for name,p in c.get('providers',{}).items():
        if any(k in p for k in ('api_key','password','token')):raise ValueError('Use api_key_env, never put secrets in config')
        u=urlsplit(p.get('base_url',p.get('url','')))
        if u.scheme!='https' and not(u.scheme=='http' and u.hostname in ('localhost','127.0.0.1','::1')):raise ValueError('API requires HTTPS or a loopback HTTP endpoint')
        if u.username or u.password:raise ValueError('Credentials do not belong in URLs')
    for key in ('catalog','material_manifest'):
        if c.get(key):c[key]=str((path.parent/Path(c[key])).resolve())
    return c


def secret(name):
    value=os.environ.get(name or '')
    if not value:raise ValueError('Missing environment variable: '+str(name))
    return value


def example():
    return {'workspace':'runtime','auto_discover':True,'auto_send':False,
      'target':'Premium perfume, jewelry and suitable gift brands in developed markets; official business email, real product, USD/EUR100+ SKU. No invented purchase intent.',
      'api':{'base_url':'https://api.openai.com/v1','api_key_env':'OUTREACH_API_KEY','text_model':'YOUR_TEXT_MODEL','image_model':'YOUR_IMAGE_MODEL'},
      'brands':[{'id':'brand-a','name':'My packaging company','sender':'hello@example.com','whatsapp':'15555550100','signature':'Your name | Your packaging company','smtp_host':'smtp.example.com','smtp_port':465,'imap_host':'imap.example.com','imap_port':993,'password_env':'BRAND_A_MAIL_PASSWORD'}],
      'concurrency':{'research':1,'concept':2,'draft':1,'send':1},'source_mode':'direct_https','material_manifest':None}
