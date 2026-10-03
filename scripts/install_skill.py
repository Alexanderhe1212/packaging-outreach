#!/usr/bin/env python3
import argparse,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--target',required=True);a=p.parse_args()
src=Path(__file__).resolve().parents[1]/'skills/packaging-outreach';dst=Path(a.target).expanduser()/'packaging-outreach'
if dst.exists():raise SystemExit('Target already exists; inspect before replacing: '+str(dst))
dst.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(src,dst)
print('Installed '+str(dst))
