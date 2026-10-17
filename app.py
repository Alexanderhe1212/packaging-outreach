#!/usr/bin/env python3
"""OutreachPilot - AI 外贸开发信工作台。

  outreach go        （或 outreach 开工）一键开工：自动启动后台、开始所有账号、报告状态
  outreach stop      （或 outreach 收工）暂停所有账号
  outreach open      打开界面窗口
  outreach replies   最近的客户回复
  outreach find X    按客户邮箱/域名/公司查当时发了什么（邮件、效果图、回复的本地文件）

  python3 app.py                 启动并打开窗口（已在运行则直接打开窗口）
  python3 app.py --no-browser    只启动后台服务
  python3 app.py status          查看各账号状态
  python3 app.py start [账号]     开始（不写账号=全部）
  python3 app.py pause [账号]     暂停
  python3 app.py add 账号 网址...  手动添加客户（官网或邮箱）
  python3 app.py usage           最近 7 天 token 与费用
  python3 app.py quit            退出后台服务
"""
import json
import contextlib
import os
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # Windows consoles may not be UTF-8: never crash on Chinese output
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
sys.path.insert(0, str(Path(__file__).resolve().parent))
from outreach import config  # noqa: E402

PORT = int(os.environ.get('OUTREACH_PORT') or config.load().get('port', 18800))
URL = 'http://127.0.0.1:%d' % PORT
APP_BROWSERS = ['Google Chrome', 'Microsoft Edge', 'Brave Browser', 'Chromium']


def call(path, data=None, timeout=30):
    req = urllib.request.Request(URL + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json', 'X-Outreach-Source': 'cli'}, method='POST' if data is not None else 'GET')
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def running():
    try:
        return call('/api/ping', timeout=1).get('ok')
    except Exception:
        return False


def open_window():
    """App-style window (no tabs / address bar) when a Chromium browser is installed, otherwise the default browser."""
    if sys.platform == 'darwin':
        for name in APP_BROWSERS:
            if Path('/Applications/%s.app' % name).exists() or Path.home().joinpath('Applications/%s.app' % name).exists():
                subprocess.Popen(['open', '-na', name, '--args', '--app=' + URL, '--window-size=1320,880'])
                return
    webbrowser.open(URL)


@contextlib.contextmanager
def process_lock(name, blocking=True):
    """OS-owned advisory lock; released on crash, never inferred from stale PID files."""
    with open(config.data_dir() / name, 'a+b') as lock:
        if sys.platform == 'win32':
            import msvcrt
            import time
            if lock.seek(0, 2) == 0:
                lock.write(b'\0'); lock.flush()
            while True:
                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if not blocking:
                        yield False
                        return
                    time.sleep(.05)
            try:
                yield True
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def ensure_running():
    """Serialize simultaneous desktop/CLI launches, without starting account work."""
    if running():
        return True
    with process_lock('launcher.lock'):
        if running():
            return True
        log = config.data_dir() / 'app.log'
        with open(log, 'ab') as out:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--no-browser'], stdout=out, stderr=out,
                             stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(Path(__file__).resolve().parent))
        import time
        for _ in range(60):
            if running():
                return True
            time.sleep(0.25)
        return False


def print_status():
    st = call('/api/state')
    for a in st['accounts']:
        s = a['stats']
        print('%-6s %-4s 今日 SMTP 接受 %s/%s  待发 %s  准备中 %s  已回复 %s  今日费用 $%s\n       %s%s' % (
            a['id'], '暂停' if a['paused'] else '运行', s.get('accepted_today', 0), a['daily_limit'] or '不限', s.get('ready', 0),
            sum(s.get(k, 0) for k in ('queued', 'researching', 'writing', 'imaging')), s.get('replied', 0), s.get('cost_today', 0),
            a['activity'], ('\n       ⚠ ' + a['error']) if a['error'] else ''))
    if st.get('legacy_running'):
        print('⚠ 旧版开发信程序仍在运行（端口 %s），请关闭以免重复发信' % st['legacy_running'])
    print('SMTP 接受不等于送达；未知结果请在界面单独核实。')
    print('界面：' + URL)


def cli(cmd, args):
    cmd = {'开工': 'go', '收工': 'stop', '状态': 'status', '回复': 'replies'}.get(cmd, cmd)
    if cmd in ('help', '-h'):
        print(__doc__)
        return 0
    if cmd in ('go', 'open') and not ensure_running():
        print('后台服务启动失败，查看日志：%s' % (config.data_dir() / 'app.log'))
        return 1
    if not running():
        print('OutreachPilot 没有在运行。一键开工：outreach go')
        return 1
    if cmd == 'go':
        call('/api/start', {'account': args[0]} if args else {})
        import time
        time.sleep(2)
        print('已开工 ✓')
        print_status()
    elif cmd == 'stop':
        call('/api/pause', {'account': args[0]} if args else {})
        print('已暂停所有账号（后台仍在检查回复）。继续：outreach go')
    elif cmd == 'open':
        from datetime import datetime, timezone
        print('%s desktop open: service ready %s' % (datetime.now(timezone.utc).isoformat(), URL), flush=True)
        open_window()
    elif cmd == 'find':
        from urllib.parse import quote
        items = call('/api/leads?limit=10&q=' + quote(' '.join(args)))['items']
        if not items:
            print('没有找到：' + ' '.join(args))
        for l in items:
            d = call('/api/lead/%d' % l['id'])
            plan = d['data'].get('plan') or {}
            print('■ %s <%s>  %s  %s' % (l['company'], l['email'], l['account'], l['status']))
            print('  主题：%s' % l['subject'])
            print('  A：%s   B：%s' % ((plan.get('a') or {}).get('name', ''), (plan.get('b') or {}).get('name', '')))
            for f in d['data'].get('files', []):
                print('  邮件：' + f)
            if d.get('has_image'):
                print('  效果图：%s/image/%d' % (URL, l['id']))
            for r in d['data'].get('replies', []):
                print('  回复：' + r['file'])
            print('  预览：%s/preview/%d\n' % (URL, l['id']))
    elif cmd == 'replies':
        for l in call('/api/leads?status=replied&limit=%s' % (args[0] if args else 10))['items']:
            d = call('/api/lead/%d' % l['id'])
            print('■ %s <%s>（%s）\n  %s\n' % (l['company'], l['email'], l['account'], (d.get('reply_excerpt') or '').strip()[:500].replace('\n', '\n  ')))
    elif cmd == 'status':
        print_status()
    elif cmd in ('start', 'pause'):
        call('/api/' + cmd, {'account': args[0]} if args else {})
        print('ok')
    elif cmd == 'add':
        print(call('/api/add', {'account': args[0], 'urls': '\n'.join(args[1:])}))
    elif cmd == 'usage':
        print(json.dumps(call('/api/usage'), ensure_ascii=False, indent=1))
    elif cmd == 'quit':
        call('/api/quit', {})
        print('已退出')
    else:
        print(__doc__)
    return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if args:
        sys.exit(cli(args[0], args[1:]))
    # Hold the service lock before startup can recover jobs or start account workers.
    with process_lock('service.lock', blocking=False) as acquired:
        if not acquired:
            if '--no-browser' not in sys.argv and ensure_running():
                open_window()
            return
        if running():
            if '--no-browser' not in sys.argv:
                open_window()
            return
        from outreach import server
        httpd = server.serve(PORT)
        if httpd is None:
            print('端口 %d 被占用' % PORT, flush=True)
            sys.exit(1)
        print('OutreachPilot 已启动：%s' % URL, flush=True)
        if '--no-browser' not in sys.argv:
            import threading
            threading.Timer(0.8, open_window).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()


if __name__ == '__main__':
    main()
