"""The same interface can be called by a terminal, agent, or localhost HTTP client."""
import argparse,json,os,signal,threading
from pathlib import Path
from .config import load,example
from .engine import Engine
from . import mail
from .providers import provider_for

def doctor(c):
    issues=[]
    for key in set(('research','text','image'))|set(c['providers']):
        p=c['providers'].get(key,{})
        if p.get('api_key_env') and not os.environ.get(p['api_key_env']):issues.append('Missing '+p['api_key_env'])
        if p.get('kind')!='agent_http' and (not p.get('model') or p['model'].startswith('YOUR_')):issues.append('Configure '+key+' model')
    if c['providers']['research']['kind']=='chat':issues.append('Research requires web-enabled responses or agent_http')
    mode=c.get('workflow',{}).get('mode','balanced')
    visual=provider_for(c,'identity' if mode=='economy' else 'draft')
    if visual.get('vision') is False:issues.append('Configure a vision-capable provider for product identity')
    for b in c['brands']:
        if c.get('auto_send') and not os.environ.get(b['password_env']):issues.append('Missing '+b['password_env'])
    return {'ready':not issues,'issues':issues,'mode':'automatic_send' if c.get('auto_send') else 'prepare_and_export','workflow_mode':mode,
      'capabilities':{'research':'live search provider or agent','planning':'text-only model','visual_identity':'vision-capable model','concept':'reference-image generation'},'compatibility_verified':'local configuration only; actual API response required'}

def main(argv=None):
    p=argparse.ArgumentParser(prog='packaging-outreach');p.add_argument('--config',default='outreach.json')
    sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('directory')
    sub.add_parser('doctor');sub.add_parser('status');sub.add_parser('start');sub.add_parser('pause');sub.add_parser('metrics')
    run=sub.add_parser('run');run.add_argument('--until-idle',action='store_true')
    serve=sub.add_parser('serve');serve.add_argument('--port',type=int,default=8787)
    seed=sub.add_parser('enqueue');seed.add_argument('candidate_json');seed.add_argument('--brand',required=True);seed.add_argument('--followup-of');seed.add_argument('--reason')
    event=sub.add_parser('event');event.add_argument('recipient');event.add_argument('kind',choices=['reply','unsubscribe','hard_reject']);event.add_argument('--evidence',required=True)
    test=sub.add_parser('mailbox-test');test.add_argument('--brand',required=True);test.add_argument('--image',required=True)
    verify=sub.add_parser('verify-mailbox-test');verify.add_argument('--brand',required=True)
    sync=sub.add_parser('sync');sync.add_argument('--brand',required=True)
    args=p.parse_args(argv)
    if args.command=='init':
        d=Path(args.directory);d.mkdir(parents=True,exist_ok=True);path=d/'outreach.json'
        with path.open('x') as f:json.dump(example(),f,indent=2,ensure_ascii=False)
        print(json.dumps({'config':str(path),'next':'Set API models/base URL, profile and environment variables; run doctor'}));return
    c=load(args.config);e=Engine(c)
    if args.command=='doctor':result=doctor(c)
    elif args.command=='status':result=e.status()
    elif args.command=='metrics':result=e.status()['performance']
    elif args.command in ('start','pause'):
        if args.command=='start':
            report=doctor(c)
            if not report['ready']:raise ValueError('; '.join(report['issues']))
        result={'paused':e.store.setting('paused','false' if args.command=='start' else 'true')=='true'}
    elif args.command=='enqueue':
        if args.brand not in e.brands:raise ValueError('Unknown brand')
        data=json.loads(Path(args.candidate_json).read_text());verified=e.verify(data['candidate'],data.get('pages',[]),e.brands[args.brand])
        result={'job_id':e.store.add(args.brand,verified,'concept',args.followup_of,args.reason)}
    elif args.command=='event':e.store.event(args.recipient,args.kind,args.evidence);result={'recorded':True}
    elif args.command=='mailbox-test':result=mail.mailbox_test(e.store,e.brands[args.brand],Path(args.image).read_bytes())
    elif args.command=='verify-mailbox-test':result=mail.verify_mailbox_test(e.store,e.brands[args.brand])
    elif args.command=='sync':result=mail.sync(e.store,e.brands[args.brand])
    elif args.command=='serve':
        from .server import serve
        serve(e,args.port);return
    else:
        report=doctor(c)
        if not report['ready']:raise ValueError('; '.join(report['issues']))
        stop=threading.Event();signal.signal(signal.SIGINT,lambda *a:stop.set());signal.signal(signal.SIGTERM,lambda *a:stop.set())
        e.run(stop=stop,until_idle=args.until_idle);result=e.status()
    print(json.dumps(result,ensure_ascii=False,indent=2))
