#!/usr/bin/env python3
"""OutreachPilot - AI 外贸开发信工作台。

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
import os
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from outreach import config  # noqa: E402

PORT = int(os.environ.get('OUTREACH_PORT') or config.load().get('port', 18800))
URL = 'http://127.0.0.1:%d' % PORT
APP_BROWSERS = ['Google Chrome', 'Microsoft Edge', 'Brave Browser', 'Chromium']


def call(path, data=None):
    req = urllib.request.Request(URL + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'}, method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def running():
    try:
        return call('/api/ping').get('ok')
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


def cli(cmd, args):
    if cmd in ('help', '-h'):
        print(__doc__)
        return 0
    if not running():
        print('OutreachPilot 没有在运行，先执行：python3 app.py')
        return 1
    if cmd == 'status':
        for a in call('/api/state')['accounts']:
            s = a['stats']
            print('%-8s %-6s 今日已发 %s/%s  待发 %s  已回复 %s  今日费用 $%s  | %s' % (
                a['id'], '暂停' if a['paused'] else '运行', s.get('sent_today', 0), a['daily_limit'], s.get('ready', 0),
                s.get('replied', 0), s.get('cost_today', 0), a['activity']))
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
    if running():
        print('OutreachPilot 已在运行：' + URL)
        open_window()
        return
    from outreach import server
    httpd = server.serve(PORT)
    if httpd is None:
        print('端口 %d 被占用' % PORT)
        sys.exit(1)
    print('OutreachPilot 已启动：%s   （关闭此窗口或在界面里点「退出」即停止）' % URL, flush=True)
    if '--no-browser' not in sys.argv:
        import threading
        threading.Timer(0.8, open_window).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
