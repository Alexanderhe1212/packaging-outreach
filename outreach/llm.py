"""统一 AI 接口：OpenAI 兼容（官方 / 中转 / Gemini / DeepSeek / 通义 / OpenRouter…）、Anthropic Claude、本机 Codex CLI。

只用标准库。每个阶段（discover / write / image）可以选不同的连接和模型。
接口不支持的参数（response_format、reasoning_effort、图片输入…）遇到 400 会自动去掉重试，并在本次运行中记住，不再浪费调用。
每次调用的 token 用量写入 store.usage，界面上可以看到每封邮件的真实成本。
"""
import base64
import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import config

_UNSUPPORTED = {}   # (connection, model) -> set of features the endpoint rejected


class AIError(RuntimeError):
    def __init__(self, message, status=None, fatal=False, setup=False):
        super().__init__(message)
        self.status = status
        self.fatal = fatal  # bad key / no quota: pause the account instead of retrying forever
        self.setup = setup  # not configured yet: wait and start by itself once settings are saved


def _ctx():
    try:
        import certifi  # optional; python.org builds on macOS sometimes lack root certificates
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _error_message(text):
    try:
        j = json.loads(text)
        e = j.get('error', j) if isinstance(j, dict) else j
        if isinstance(e, dict):
            return str(e.get('message') or e)
        return str(e)
    except ValueError:
        return text[:300]


def http_json(url, body, headers, timeout=300, attempts=3, content_type='application/json'):
    last = None
    for n in range(attempts):
        h = dict(headers, **{'Content-Type': content_type, 'Accept': 'application/json'})
        req = urllib.request.Request(url, data=body, method='POST', headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            text = e.read().decode('utf-8', 'replace')[:1500]
            msg = _error_message(text) or 'HTTP %s' % e.code
            low = text.lower()
            if e.code in (401, 403) or 'insufficient_quota' in low or 'billing' in low or 'credit balance' in low:
                raise AIError('API 鉴权或额度问题：' + msg, e.code, fatal=True)
            if e.code in (408, 409, 429, 500, 502, 503, 504, 520, 522, 524, 529) and n < attempts - 1:
                time.sleep(4 * (n + 1) ** 2)
                last = AIError(msg, e.code)
                continue
            raise AIError(msg, e.code)
        except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError, OSError) as e:
            last = AIError('网络错误：%s' % getattr(e, 'reason', e))
            if n < attempts - 1:
                time.sleep(5 * (n + 1))
    raise last or AIError('API 请求失败')


def extract_json(text):
    text = (text or '').strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    m = re.search(r'```(?:json)?\s*([\[{].*?[\]}])\s*```', text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except ValueError:
            pass
    for opener, closer in (('{', '}'), ('[', ']')):
        start = text.find(opener)
        while start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == opener:
                    depth += 1
                elif text[i] == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except ValueError:
                            break
            start = text.find(opener, start + 1)
    raise AIError('模型没有返回有效 JSON：' + text[:160])


def mime(raw):
    if raw[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return 'image/webp'
    if raw[:3] == b'GIF':
        return 'image/gif'
    return 'image/jpeg'


def multipart(fields, files):
    boundary = '----op' + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode('utf-8'))
    for k, (name, data, ctype) in files.items():
        out.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: %s\r\n\r\n'
                    % (boundary, k, name, ctype)).encode('utf-8') + data + b'\r\n')
    out.append(('--%s--\r\n' % boundary).encode())
    return b''.join(out), 'multipart/form-data; boundary=' + boundary


def connection_info(name, cfg=None):
    cfg = cfg or config.load()
    conn = dict(cfg['connections'].get(name) or {})
    if not conn:
        raise AIError('没有名为 %s 的 API 连接（设置 → AI 接口）' % name, fatal=True, setup=True)
    preset = cfg.get('api_presets', {}).get(conn.get('preset'), {})
    conn.setdefault('kind', preset.get('kind', 'openai'))
    conn['base_url'] = (conn.get('base_url') or preset.get('base_url') or '').rstrip('/')
    conn['preset_info'] = preset
    conn['name'] = name
    conn['key'] = config.secrets()['keys'].get(name, '')
    return conn


class Stage:
    """One configured pipeline stage. Usage: Stage('write', account_id).json(system, user, image=jpeg_bytes)."""

    def __init__(self, stage, account='', cfg=None):
        cfg = cfg or config.load()
        self.stage = stage
        self.account = account
        self.opts = dict(cfg['stages'].get(stage) or {})
        self.conn = connection_info(self.opts.get('connection', 'main'), cfg)
        self.kind = self.conn['kind']
        self.model = (self.opts.get('model') or '').strip()
        self.timeout = float(self.opts.get('timeout', 300))
        if not self.model:
            raise AIError('阶段 %s 没有设置模型' % stage, fatal=True, setup=True)
        if self.kind != 'codex' and not self.conn['key'] and not self.conn['preset_info'].get('nokey'):
            raise AIError('还没有填写「%s」连接的 API Key（设置 → AI 接口）' % self.conn['name'], fatal=True, setup=True)
        if self.kind != 'codex' and not self.conn['base_url']:
            raise AIError('「%s」连接没有填写 Base URL' % self.conn['name'], fatal=True, setup=True)

    # ---------- bookkeeping ----------
    @property
    def _bad(self):
        return _UNSUPPORTED.setdefault((self.conn['name'], self.model), set())

    def _record(self, inp=0, out=0, cached=0, images=0, searches=0):
        try:
            from . import store
            store.add_usage(self.account, self.stage, self.model, inp, out, cached, images, searches,
                            quality=self.opts.get('quality', ''))
        except Exception:
            pass

    @property
    def can_search(self):
        return bool(self.opts.get('web_search', True)) and bool(self.conn['preset_info'].get('search', True))

    # ---------- public API ----------
    def json(self, system, user, image=None, search=False, max_tokens=4000):
        text = self.text(system, user, image=image, search=search, max_tokens=max_tokens, want_json=True)
        return extract_json(text)

    def text(self, system, user, image=None, search=False, max_tokens=4000, want_json=False):
        search = search and self.can_search
        if self.kind == 'anthropic':
            return self._anthropic(system, user, image, search, max_tokens)
        if self.kind == 'codex':
            return self._codex(system, user, image, search)
        return self._openai(system, user, image, search, want_json)

    # ---------- OpenAI compatible ----------
    def _headers(self):
        h = {'Authorization': 'Bearer ' + self.conn['key']}
        if 'openrouter.ai' in self.conn['base_url']:
            h.update({'HTTP-Referer': 'https://github.com/Alexanderhe1212/packaging-outreach', 'X-Title': 'OutreachPilot'})
        return h

    def _openai(self, system, user, image, search, want_json):
        preset = self.conn['preset_info']
        if search and not (preset.get('search_param') or preset.get('search_suffix')) and 'responses' not in self._bad:
            try:
                return self._responses(system, user, image)
            except AIError as e:
                if e.fatal or e.status not in (400, 404, 405, 415, 422, 501):
                    raise
                self._bad.add('responses')  # relay without /responses: fall back to chat (+ site crawling does the rest)
        model = self.model
        extra = {}
        if search and preset.get('search_suffix') and not model.endswith(preset['search_suffix']):
            model += preset['search_suffix']
        if search and preset.get('search_param'):
            extra.update(preset['search_param'])
        use_image = image is not None and self.opts.get('vision', True) and 'vision' not in self._bad
        content = user
        if use_image:
            content = [{'type': 'text', 'text': user},
                       {'type': 'image_url', 'image_url': {'url': 'data:%s;base64,%s' % (mime(image), base64.b64encode(image).decode()),
                                                           'detail': 'low'}}]
        payload = dict(model=model, messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': content}], **extra)
        optional = []
        if want_json and 'response_format' not in self._bad:
            payload['response_format'] = {'type': 'json_object'}
            optional.append('response_format')
        effort = self.opts.get('effort')
        if effort and 'reasoning_effort' not in self._bad and preset.get('kind', 'openai') == 'openai' and self.conn.get('preset') in ('openai', 'relay', None):
            payload['reasoning_effort'] = effort
            optional.append('reasoning_effort')
        for k in extra:
            optional.append(k)
        while True:
            try:
                r = http_json(self.conn['base_url'] + '/chat/completions', json.dumps(payload).encode(), self._headers(), self.timeout)
                break
            except AIError as e:
                if e.fatal or e.status not in (400, 422):
                    raise
                msg = str(e).lower()
                if use_image and any(w in msg for w in ('image', 'vision', 'multimodal', 'content type', 'image_url')):
                    self._bad.add('vision')
                    payload['messages'][1]['content'] = user
                    use_image = False
                    continue
                hit = next((k for k in optional if k.replace('_', ' ') in msg or k in msg), None) or (optional[0] if optional else None)
                if not hit:
                    raise
                optional.remove(hit)
                payload.pop(hit, None)
                self._bad.add(hit)
        u = r.get('usage') or {}
        self._record(u.get('prompt_tokens', 0), u.get('completion_tokens', 0),
                     (u.get('prompt_tokens_details') or {}).get('cached_tokens', 0) or 0)
        try:
            return r['choices'][0]['message'].get('content') or ''
        except (KeyError, IndexError, TypeError):
            raise AIError('接口返回格式异常：' + json.dumps(r)[:200])

    def _responses(self, system, user, image):
        content = [{'type': 'input_text', 'text': user}]
        if image is not None and self.opts.get('vision', True):
            content.append({'type': 'input_image', 'image_url': 'data:%s;base64,%s' % (mime(image), base64.b64encode(image).decode()),
                            'detail': 'low'})
        payload = {'model': self.model, 'instructions': system, 'input': [{'role': 'user', 'content': content}],
                   'tools': [{'type': 'web_search'}]}
        if self.opts.get('effort') and 'reasoning_effort' not in self._bad:
            payload['reasoning'] = {'effort': self.opts['effort']}
        try:
            r = http_json(self.conn['base_url'] + '/responses', json.dumps(payload).encode(), self._headers(), self.timeout)
        except AIError as e:
            if e.status == 400 and 'reasoning' in payload and 'reason' in str(e).lower():
                self._bad.add('reasoning_effort')
                payload.pop('reasoning')
                r = http_json(self.conn['base_url'] + '/responses', json.dumps(payload).encode(), self._headers(), self.timeout)
            else:
                raise
        u = r.get('usage') or {}
        searches = sum(1 for it in r.get('output', []) if it.get('type') == 'web_search_call')
        self._record(u.get('input_tokens', 0), u.get('output_tokens', 0),
                     (u.get('input_tokens_details') or {}).get('cached_tokens', 0) or 0, searches=searches)
        if isinstance(r.get('output_text'), str):
            return r['output_text']
        parts = []
        for item in r.get('output', []):
            if item.get('type') == 'message':
                parts += [c.get('text', '') for c in item.get('content', []) if c.get('type') in ('output_text', 'text')]
        return '\n'.join(parts)

    # ---------- Anthropic Claude (raw HTTP: the app ships without third-party packages) ----------
    def _anthropic(self, system, user, image, search, max_tokens):
        base = self.conn['base_url']
        url = base + ('/messages' if base.endswith('/v1') else '/v1/messages')
        headers = {'x-api-key': self.conn['key'], 'anthropic-version': '2023-06-01'}
        content = []
        if image is not None and self.opts.get('vision', True):
            content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': mime(image),
                                                         'data': base64.b64encode(image).decode()}})
        content.append({'type': 'text', 'text': user})
        payload = {'model': self.model, 'max_tokens': max_tokens,
                   'system': [{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
                   'messages': [{'role': 'user', 'content': content}]}
        if self.opts.get('effort') and 'effort' not in self._bad:
            payload['output_config'] = {'effort': self.opts['effort']}
        official = 'api.anthropic.com' in base
        if official and 'fallbacks' not in self._bad and re.match(r'claude-(opus-5|fable-5|sonnet-5-5)', self.model):
            payload['fallbacks'] = 'default'  # server-side fallback model if a safety classifier declines
            headers['anthropic-beta'] = 'server-side-fallback-2026-07-01'
        tool_types = ['web_search_20260209', 'web_search_20250305']
        if search:
            payload['tools'] = [{'type': tool_types[0] if 'search_v1' not in self._bad else tool_types[1],
                                 'name': 'web_search', 'max_uses': 5}]
        totals = [0, 0, 0, 0]
        texts = []
        for _turn in range(4):  # pause_turn: long server-tool turns are resumed by re-sending
            try:
                r = http_json(url, json.dumps(payload).encode(), headers, self.timeout)
            except AIError as e:
                if e.fatal or e.status != 400:
                    raise
                msg = str(e).lower()
                if 'fallback' in msg and 'fallbacks' in payload:
                    self._bad.add('fallbacks')
                    payload.pop('fallbacks')
                    headers.pop('anthropic-beta', None)
                elif 'effort' in msg or 'output_config' in msg:
                    self._bad.add('effort')
                    payload.pop('output_config', None)
                elif search and payload['tools'][0]['type'] == tool_types[0] and ('web_search' in msg or 'tool' in msg):
                    self._bad.add('search_v1')
                    payload['tools'][0]['type'] = tool_types[1]
                elif image is not None and 'image' in msg and content[0].get('type') == 'image':
                    content.pop(0)
                else:
                    raise
                continue
            u = r.get('usage') or {}
            totals[0] += u.get('input_tokens', 0) + u.get('cache_read_input_tokens', 0) + u.get('cache_creation_input_tokens', 0)
            totals[1] += u.get('output_tokens', 0)
            totals[2] += u.get('cache_read_input_tokens', 0)
            totals[3] += (u.get('server_tool_use') or {}).get('web_search_requests', 0)
            texts += [b.get('text', '') for b in r.get('content', []) if b.get('type') == 'text']
            if r.get('stop_reason') == 'refusal':
                raise AIError('模型拒绝了这个请求（refusal）')
            if r.get('stop_reason') != 'pause_turn':
                break
            payload['messages'] = payload['messages'][:1] + [{'role': 'assistant', 'content': r.get('content', [])}]
        self._record(totals[0], totals[1], totals[2], searches=totals[3])
        return '\n'.join(texts)

    # ---------- local Codex CLI (uses the ChatGPT subscription) ----------
    def _codex(self, system, user, image, search):
        cli = self.conn.get('cli_path') or shutil.which('codex') or os.path.expanduser('~/.local/bin/codex')
        if not os.path.exists(cli):
            raise AIError('没找到 codex 命令，请先安装并登录 Codex CLI', fatal=True)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'answer.txt'
            args = [cli, 'exec', '--skip-git-repo-check', '--ephemeral', '--sandbox', 'read-only', '--color', 'never',
                    '-C', d, '-m', self.model, '-c', 'model_reasoning_effort="%s"' % (self.opts.get('effort') or 'low'),
                    '-c', 'web_search="%s"' % ('live' if search else 'disabled'), '-c', 'project_doc_max_bytes=0', '-o', str(out)]
            if image is not None and self.opts.get('vision', True):
                img = Path(d) / ('product' + {'image/png': '.png', 'image/webp': '.webp'}.get(mime(image), '.jpg'))
                img.write_bytes(image)
                args += ['-i', str(img)]
            prompt = system + '\n\n' + user
            try:
                p = subprocess.run(args, input=prompt.encode('utf-8'), capture_output=True, timeout=self.timeout or 600)
            except subprocess.TimeoutExpired:
                raise AIError('Codex 超时')
            if p.returncode != 0 or not out.exists():
                err = (p.stderr or p.stdout).decode('utf-8', 'replace')[-300:]
                fatal = 'login' in err.lower() or 'auth' in err.lower()
                raise AIError('Codex 调用失败：' + err.strip(), fatal=fatal)
            self._record(len(prompt) // 4, out.stat().st_size // 4)  # CLI does not report usage here; rough estimate
            return out.read_text(encoding='utf-8')

    # ---------- image generation ----------
    def image(self, prompt, reference=None):
        if self.kind != 'openai' or not self.conn['preset_info'].get('image', True):
            raise AIError('「%s」连接不支持生图，请在 设置 → AI 接口 给「效果图」选择支持生图的连接（如 OpenAI / 中转）' % self.conn['name'], fatal=True)
        size = self.opts.get('size', '1536x1024')
        quality = self.opts.get('quality', 'medium')
        base, headers = self.conn['base_url'], self._headers()
        if reference is not None and 'edits' not in self._bad:
            fields = dict(model=self.model, prompt=prompt, size=size, quality=quality, n='1', input_fidelity='high',
                          output_format='jpeg', output_compression='88')
            optional = ['input_fidelity', 'output_compression', 'output_format', 'quality']
            while True:
                body, ctype = multipart(fields, {'image': ('product' + {'image/png': '.png', 'image/webp': '.webp'}.get(mime(reference), '.jpg'),
                                                           reference, mime(reference))})
                try:
                    r = http_json(base + '/images/edits', body, headers, self.timeout, attempts=2, content_type=ctype)
                    self._record(images=1)
                    return self._image_bytes(r)
                except AIError as e:
                    if e.fatal:
                        raise
                    if e.status == 400 and optional:
                        fields.pop(optional.pop(0), None)
                        continue
                    if e.status in (400, 404, 405, 501):  # no reference-image editing here: plain generation
                        self._bad.add('edits')
                        break
                    raise
        payload = dict(model=self.model, prompt=prompt, size=size, quality=quality, n=1, output_format='jpeg', output_compression=88)
        optional = ['output_compression', 'output_format', 'quality']
        while True:
            try:
                r = http_json(base + '/images/generations', json.dumps(payload).encode(), headers, self.timeout, attempts=2)
                self._record(images=1)
                return self._image_bytes(r)
            except AIError as e:
                if e.fatal or e.status != 400 or not optional:
                    raise
                payload.pop(optional.pop(0), None)
                if not optional:
                    payload['response_format'] = 'b64_json'

    def _image_bytes(self, r):
        item = (r.get('data') or [{}])[0]
        if item.get('b64_json'):
            return base64.b64decode(item['b64_json'])
        if item.get('url'):
            from .web import get
            return get(item['url'], accept='image/*', max_bytes=25 * 1024 * 1024)[0]
        raise AIError('图片接口没有返回图片')


def test_connection(name):
    """Cheapest possible round trip for the settings page."""
    cfg = config.load()
    conn = connection_info(name, cfg)
    preset = conn['preset_info']
    model = next((s['model'] for s in cfg['stages'].values() if s.get('connection') == name and s.get('model') and 'image' not in s['model']),
                 (preset.get('models') or ['gpt-5-mini'])[0])
    cfg = config.merge(cfg, {'stages': {'_test': {'connection': name, 'model': model, 'effort': 'low'}}})
    st = Stage('_test', cfg=cfg)
    t0 = time.time()
    r = st.json('Reply with JSON only.', 'Return {"ok": true}', max_tokens=50)
    return {'ok': bool(r.get('ok')), 'model': model, 'seconds': round(time.time() - t0, 1)}
