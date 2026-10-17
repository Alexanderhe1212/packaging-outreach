"""Local JSON adapter around the unchanged GPL-2.0 theHarvester parser.

This worker performs no network operations. See provenance.json/LICENSE-pinned.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import re
import sys

spec=importlib.util.spec_from_file_location('upstream_harvester_parser',Path(__file__).parent/'vendor/myparser.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
data=json.loads(sys.stdin.read(1_000_000))
domain=data['domain']
if not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+',domain):raise ValueError('Invalid domain')
parser=module.Parser(data['text'],re.escape(domain))
values=asyncio.run(parser.emails())
emails=[]
for value in sorted(v for v in values if isinstance(v,str)):
    if not re.fullmatch(r'[^\s;@]+@[^\s;@]+\.[^\s;@]+',value):continue
    email_domain=value.rsplit('@',1)[1]
    if email_domain!=domain and not email_domain.endswith('.'+domain):continue
    # Upstream's domain regex can otherwise truncate .com.evil to .com.
    if not re.search(r'(?<![\w.+-])'+re.escape(value)+r'(?![\w.-])',parser.results,re.I):continue
    emails.append(value)
print(json.dumps({'emails':emails[:20]}))
