"""配置：仓库内 defaults.json + profiles/*.json 为默认值；用户设置与密钥保存在数据目录（不进 Git、不放 iCloud）。

数据目录：macOS ~/Library/Application Support/OutreachPilot，其它系统 ~/.outreach-pilot，可用 OUTREACH_DATA 覆盖。
"""
import copy
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_lock = threading.RLock()


def data_dir():
    if os.environ.get('OUTREACH_DATA'):
        d = Path(os.path.expanduser(os.environ['OUTREACH_DATA']))
    elif sys.platform == 'darwin':
        d = Path.home() / 'Library' / 'Application Support' / 'OutreachPilot'
    else:
        d = Path.home() / '.outreach-pilot'
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return copy.deepcopy(default)


def write_json(path, value, private=False):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


# ---------------- settings ----------------
def defaults():
    return read_json(ROOT / 'defaults.json', {})


def load():
    """Effective settings: defaults.json merged with the user's settings.json. Accounts are a list (replaced, not merged)."""
    with _lock:
        user = read_json(data_dir() / 'settings.json', {})
        cfg = merge(defaults(), {k: v for k, v in user.items() if k != 'accounts'})
        cfg['accounts'] = user.get('accounts', [])
        return cfg


def save(patch):
    """Merge a patch into settings.json. 'accounts' replaces the whole list."""
    with _lock:
        path = data_dir() / 'settings.json'
        cur = read_json(path, {})
        accounts = patch.pop('accounts', None) if isinstance(patch, dict) else None
        cur = merge(cur, patch)
        if accounts is not None:
            cur['accounts'] = accounts
        write_json(path, cur)
        return load()


def account(acc_id):
    for a in load()['accounts']:
        if a['id'] == acc_id:
            return a
    raise KeyError('账号不存在：%s' % acc_id)


# ---------------- secrets ----------------
def secrets():
    s = read_json(data_dir() / 'secrets.json', {})
    s.setdefault('keys', {})
    s.setdefault('passwords', {})
    for k, v in os.environ.items():  # env vars win: OUTREACH_KEY_<CONNECTION>, OUTREACH_PASSWORD_<ACCOUNT>
        if k.startswith('OUTREACH_KEY_'):
            s['keys'][k[13:].lower()] = v
        elif k.startswith('OUTREACH_PASSWORD_'):
            s['passwords'][k[18:]] = v
    return s


def save_secrets(keys=None, passwords=None):
    """Blank values keep what is stored, so the UI never has to echo a secret back. '-' deletes."""
    with _lock:
        path = data_dir() / 'secrets.json'
        cur = read_json(path, {})
        for group, values in (('keys', keys), ('passwords', passwords)):
            bucket = cur.setdefault(group, {})
            for k, v in (values or {}).items():
                if v == '-':
                    bucket.pop(k, None)
                elif v:
                    bucket[k] = v.strip()
        write_json(path, cur, private=True)


# ---------------- product profiles ----------------
def profiles():
    """Built-in profiles in ./profiles, overridden/extended by <data>/profiles/*.json."""
    out = {}
    for folder in (ROOT / 'profiles', data_dir() / 'profiles'):
        for f in sorted(folder.glob('*.json')) if folder.exists() else []:
            p = read_json(f)
            if p and p.get('id'):
                out[p['id']] = merge(out.get(p['id'], {}), p)
    return out


def profile(pid):
    ps = profiles()
    return ps.get(pid) or ps.get('packaging') or next(iter(ps.values()))


def save_profile(p):
    d = data_dir() / 'profiles'
    d.mkdir(exist_ok=True)
    write_json(d / ('%s.json' % p['id']), p)


def resolve(path):
    p = Path(os.path.expanduser(str(path)))
    return p if p.is_absolute() else data_dir() / p
