"""把 skills/outreach-pilot 安装到 Claude Code（~/.claude/skills）和 Codex（~/.codex/skills）。用法：python3 scripts/install_skill.py"""
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / 'skills' / 'outreach-pilot'
APP_ROOT = sys.argv[sys.argv.index('--root') + 1] if '--root' in sys.argv else str(SRC.parent.parent)

for base in (Path.home() / '.claude' / 'skills', Path.home() / '.codex' / 'skills'):
    if not base.parent.exists():
        continue
    dst = base / 'outreach-pilot'
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(SRC, dst)
    text = (dst / 'SKILL.md').read_text(encoding='utf-8').replace('<repo>', APP_ROOT)
    (dst / 'SKILL.md').write_text(text, encoding='utf-8')
    print('installed', dst)
