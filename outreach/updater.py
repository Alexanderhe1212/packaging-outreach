"""一键更新：从 GitHub 拉取最新版本。git 安装用 git pull；下载安装则替换代码文件（数据和设置不在代码目录，不受影响）。"""
import io
import re
import shutil
import subprocess
import zipfile

from . import REPO, VERSION
from .config import ROOT
from .web import get

KEEP = {'.git', '__pycache__', '.DS_Store'}


def _ver(s):
    return tuple(int(x) for x in re.findall(r'\d+', s)[:3])


def latest():
    raw, _, _ = get('https://raw.githubusercontent.com/%s/main/outreach/__init__.py' % REPO, accept='text/plain', timeout=15)
    m = re.search(r"VERSION\s*=\s*'([^']+)'", raw.decode('utf-8', 'replace'))
    return m.group(1) if m else VERSION


def check():
    try:
        new = latest()
    except Exception as e:
        return {'current': VERSION, 'latest': None, 'error': '无法连接 GitHub：%s' % type(e).__name__}
    return {'current': VERSION, 'latest': new, 'update': _ver(new) > _ver(VERSION),
            'mode': 'git' if (ROOT / '.git').exists() else 'zip'}


def apply():
    if (ROOT / '.git').exists() and shutil.which('git'):
        r = subprocess.run(['git', '-C', str(ROOT), 'pull', '--ff-only', 'origin', 'main'], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError('git pull 失败：' + (r.stderr or r.stdout)[-300:])
        return {'ok': True, 'log': r.stdout[-500:]}
    raw, _, _ = get('https://codeload.github.com/%s/zip/refs/heads/main' % REPO, accept='application/zip',
                    max_bytes=50 * 1024 * 1024, timeout=60)
    z = zipfile.ZipFile(io.BytesIO(raw))
    prefix = z.namelist()[0].split('/')[0] + '/'
    for name in z.namelist():
        rel = name[len(prefix):]
        if not rel or rel.split('/')[0] in KEEP:
            continue
        target = ROOT / rel
        if name.endswith('/'):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))
            if rel.endswith(('.command', '.sh')):
                target.chmod(0o755)
    return {'ok': True, 'log': 'downloaded %s' % prefix}
