"""开发流水线（每个客户最多 1 次写作调用 + 1 次生图；找客户每 6 家才 1 次调用）。

  discover  一次便宜的调用拿到一批候选域名（有联网搜索就用，没有就凭模型知识，官网抓取负责核实）
  crawl     零 token：从官网读公开邮箱、主推产品、产品图
  write     一次调用：看产品图（低精度 512px）→ 设计 A/B → 写邮件，返回 JSON
  image     一次调用：以真实产品照片为参考生成 A/B 效果图
"""
import json
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config, llm, store, web



def own_domains():
    """Our own companies (every account's sender + website domain) are never prospects."""
    out = set()
    for a in config.load()['accounts']:
        for v in (a.get('sender', '').split('@')[-1], web.host(a.get('website') or '')):
            if v:
                out.add(web.root_domain(v))
    return out


def brief(account, profile):
    return {
        'company': account.get('company_name') or account.get('name'),
        'pitch': account.get('pitch') or profile.get('offer', ''),
        'markets': account.get('markets') or profile.get('markets', ''),
        'focus': account.get('focus') or profile.get('ideal_customers', []),
    }


# ---------------- 1. discover ----------------
def discover(account, profile):
    """Ask for a batch of candidate brand domains. Returns number of new candidates queued."""
    b = brief(account, profile)
    stage = llm.Stage('discover', account['id'])
    n = int(config.load()['stages']['discover'].get('batch', 6))
    focus = random.choice(b['focus']) if b['focus'] else 'brands selling physical products'
    markets = [m.strip() for m in re.split(r'[,/;]', b['markets']) if m.strip()]
    market = random.choice(markets) if markets else 'developed markets'
    letters = random.choice(['A-E', 'F-K', 'L-P', 'Q-T', 'U-Z', 'any letter'])
    searching = stage.can_search
    system = ('You find B2B prospects for %s. What we sell: %s\n'
              'Return ONLY JSON: {"candidates":[{"brand":"Brand name","domain":"brand.com","note":"what they sell, 5-10 words"}]}\n'
              'Rules: real, currently operating brands that sell physical products and have their own website/online store; '
              'independent or small-to-mid DTC brands preferred. Exclude %s. The domain must be the brand\'s own official site '
              '(no marketplaces, social profiles or link-in-bio pages). %s'
              ) % (b['company'], b['pitch'], profile.get('exclude', 'marketplaces, giant corporations, resellers'),
                   'Use web search to confirm each site is live.' if searching else 'Only list brands you are confident exist, with their real domain.')
    skip = store.recent_candidate_domains(account['id'], 40)
    user = ('Find %d prospects. Focus: %s. Market: %s. Prefer less obvious brands (names starting %s), not the first famous results.\n'
            'Skip these domains: %s') % (n, focus, market, letters, ', '.join(skip) or '(none)')
    data = stage.json(system, user, search=searching, max_tokens=1500)
    items = data.get('candidates', data) if isinstance(data, dict) else data
    items = [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
    for i in items:
        i['domain'] = web.host(str(i.get('domain') or i.get('website') or ''))
        i['note'] = '%s | %s' % (focus[:60], i.get('note', ''))
    own = own_domains()
    items = [i for i in items if i['domain'] and web.root_domain(i['domain']) not in own]
    return store.add_candidates(account['id'], items)


# ---------------- 2. crawl ----------------
def research(account, url, email_hint='', manual=False):
    """Prospect dict + product photo bytes, read from the official site. Raises web.CrawlError."""
    try:
        p = web.crawl(url, email_hint)
    except web.CrawlError:
        if not manual:
            raise
        p = research_with_ai(account, url, email_hint)  # manual lead on a site the crawler cannot read
    if web.root_domain(p['domain']) in own_domains():
        raise web.CrawlError('自家域名')
    if store.hard_blocked(p['email'], account['id']):
        raise web.CrawlError('该邮箱已退订/退信/回复过，不再发送')
    if not manual and store.blocked(p['email'], p['domain'], account['id']):
        raise web.CrawlError('重复客户')
    img, img_url = web.product_image(p.get('product_image_url'), p.get('product_url') or None)
    if img_url:
        p['product_image_url'] = img_url
    if not manual and not (p.get('product_name') and img):
        raise web.CrawlError('官网没找到可展示的产品')  # concepts need a real product photo; skipping costs no tokens
    return p, img


def research_with_ai(account, url, email_hint):
    stage = llm.Stage('discover', account['id'])
    if not stage.can_search:
        raise web.CrawlError('官网无法自动读取，且当前接口不支持联网搜索；请手动填写邮箱')
    system = ('Research one company for a B2B proposal. Use web search and open its official pages. Return ONLY JSON with keys: '
              'company, website, email (must be printed on the company\'s own site; never guess), email_source, product_name, '
              'product_url, product_image_url (direct image URL), product_facts (list of 2-4 short facts), country.')
    d = stage.json(system, 'Company website: %s %s' % (url, ('Known email: ' + email_hint) if email_hint else ''), search=True)
    email = (email_hint or str(d.get('email') or '')).lower().strip()
    if not web.EMAIL_RE.fullmatch(email or '-'):
        raise web.CrawlError('没找到公开邮箱，请手动填写')
    site = d.get('website') or url
    return {'company': d.get('company') or web.host(site), 'customer_brand': d.get('company') or web.host(site),
            'website': web.normalize(site), 'domain': web.host(site), 'email': email, 'email_source': d.get('email_source', 'ai'),
            'country': d.get('country', ''), 'lang': '', 'site_description': '', 'product_name': d.get('product_name', ''),
            'product_url': d.get('product_url', ''), 'product_image_url': d.get('product_image_url', ''),
            'product_facts': [str(f) for f in (d.get('product_facts') or [])][:4], 'product_price': '', 'product_description': ''}


def facts_for_prompt(p):
    keep = {k: p.get(k) for k in ('customer_brand', 'country', 'site_description', 'product_name', 'product_price',
                                   'product_facts', 'product_description') if p.get(k)}
    return json.dumps(keep, ensure_ascii=False, separators=(',', ':'))


# ---------------- 3. write ----------------
EMAIL_RULES = '''EMAIL RULES - a cold first email from {contact} at {company}; it must read like a real person wrote it after looking at their product:
- Subject: 4-8 words, specific to their product, natural lowercase is fine. Tone examples: {subjects}. No "free", no "!", no fake "Re:".
- Greeting: "Hi <their brand name> team,"
- 1-2 lines: one genuine, specific observation about the product (a real fact: material, contents, size, detail) and why the {noun} matters for it. Never say their current {noun} is bad. No flattery cliches.
- Then a natural line like "I mocked up two {noun} ideas for it (image below):"
- "A - <short concept name>: <one sentence: what it is + practical benefit for THIS product>"
- "B - <short concept name>: <one sentence, clearly different structure and benefit>"
- One short line on what we do.
- Close with ONE easy question inviting a one-word reply, e.g. {cta} Vary the wording.
- No sign-off or signature (the app adds it). No links. 80-120 words. Plain, warm, confident {language}. Short paragraphs.
- Banned: "I hope this email finds you well", "I came across", "elevate", "game-changer", "synergy", "reach out", "cutting-edge", "world-class", invented statistics, guarantees, certifications, prices, lead times, factory claims, other supplier names.
- {extra}'''

OUTPUT = '''Return JSON only:
{"product_visual":"precise visual description of the product (shape, colour, material, label) so an illustrator could redraw it",
 "count":"units per package, e.g. one bottle / set of 3 jars",
 "a":{"name":"short concept name","structure":"from the library","visual":"colours, material, finish, insert, product placement, branding"},
 "b":{"name":"...","structure":"...","visual":"..."},
 "scene":"background surface and 1-2 subtle props that suit the brand, or plain",
 "subject":"...",
 "body":"full email body with \\n line breaks, starting with the greeting"}'''


def library_items(profile):
    return [l[2:].strip() for l in profile.get('concept_library', '').splitlines() if l.startswith('- ')]


def variety_note(account, profile):
    """Per-lead nudge (kept out of the cached system prompt): avoid recent structures, suggest two fresh directions."""
    recent = store.recent_structures(account['id'], 10)
    low = ' '.join(recent).lower()
    fresh = [i for i in library_items(profile) if i.split('(')[0].strip().lower()[:18] not in low] or library_items(profile)
    seeds = random.sample(fresh, min(2, len(fresh)))
    note = '\nVARIETY: '
    if recent:
        note += 'This sender recently proposed: %s. Do not repeat those structures. ' % '; '.join(recent[:8])
    if seeds:
        note += 'Fresh directions worth considering for this product: %s. ' % ' / '.join(seeds)
    return note + ('A and B must be different structure families. Make at least one concept genuinely new and memorable for this '
                   'product (an unexpected opening, reveal, shape or reuse idea) while staying practical to produce.')


def writer_prompts(account, profile, p, has_photo):
    b = brief(account, profile)
    noun = profile.get('concept_noun', 'packaging')
    # Static first (account + profile only) so providers can cache the prefix across every lead of this account.
    system = '\n\n'.join([
        'You are a senior %s designer and B2B copywriter at %s. Reply with one JSON object only.' % (noun, b['company']),
        'WHAT WE DO: ' + b['pitch'] + (('\n' + account['extra_rules']) if account.get('extra_rules') else ''),
        'CONCEPT LIBRARY:\n' + profile.get('concept_library', ''),
        'DESIGN GUIDANCE: ' + profile.get('design_guidance', ''),
        EMAIL_RULES.format(contact=account.get('contact_name', 'Hugo'), company=b['company'], noun=noun,
                           subjects='; '.join('"%s"' % s for s in profile.get('subject_examples', [])) or '"two ideas for your product"',
                           cta=' / '.join('"%s"' % s for s in profile.get('cta_examples', [])) or '"Would A or B be worth a quote?"',
                           language={'en': 'English', 'de': 'German', 'fr': 'French', 'es': 'Spanish'}.get(account.get('language', 'en'), 'English'),
                           extra=profile.get('email_extra', '')),
        OUTPUT])
    user = ('The attached photo is their real product. ' if has_photo else 'No photo available; rely on the facts. ') + \
        'Design two %s concepts for it and write the email.\nPRODUCT RESEARCH (from their website): %s' % (noun, facts_for_prompt(p)) + \
        variety_note(account, profile)
    return system, user


def clean_body(body, account):
    body = (body or '').replace('\r\n', '\n').replace('\\n', '\n').strip()
    body = re.sub(r'\n{3,}', '\n\n', body)
    body = re.sub(r'\n+(best|kind|warm)?\s*(regards|wishes|thanks|cheers|best)[,!.]?[ \t]*(\n.*)?$', '', body, flags=re.I | re.S)
    name = account.get('contact_name', '')
    if name:
        body = re.sub(r'\n+%s\s*$' % re.escape(name), '', body)
    return body.strip()


def write(account, profile, p, photo):
    system, user = writer_prompts(account, profile, p, photo is not None)
    plan = llm.Stage('write', account['id']).json(system, user, image=shrink(photo, 512) if photo else None, max_tokens=2500)
    for k in ('a', 'b'):
        v = plan.get(k) or plan.get('option_' + k)
        plan[k] = v if isinstance(v, dict) else {'name': str(v or ''), 'structure': '', 'visual': str(v or '')}
    plan['subject'] = re.sub(r'\s+', ' ', str(plan.get('subject') or '')).strip().strip('"')[:120]
    plan['body'] = clean_body(plan.get('body'), account)
    if not plan['subject'] or len(plan['body']) < 120:
        raise ValueError('邮件内容不完整')
    others = [a.get('company_name', '') for a in config.load()['accounts'] if a['id'] != account['id']]
    text = (plan['subject'] + plan['body']).lower()
    for o in others:
        if o and o.lower() in text:
            raise ValueError('邮件里出现了另一个账号的公司名')
    return plan


# ---------------- 4. image ----------------
def image_prompt(profile, p, plan):
    tpl = profile.get('image', {}).get('prompt') or '{product}\nA: {a_structure}. {a_visual}\nB: {b_structure}. {b_visual}'
    a, b = plan['a'], plan['b']
    return tpl.format(product=plan.get('product_visual') or p.get('product_name', 'the product'),
                      count=(plan.get('count') or 'One unit').capitalize(),
                      a_structure=a.get('structure') or a.get('name', ''), a_visual=a.get('visual', ''),
                      b_structure=b.get('structure') or b.get('name', ''), b_visual=b.get('visual', ''),
                      brand=p.get('customer_brand') or p.get('company', ''),
                      scene=plan.get('scene') or 'warm off-white seamless background',
                      footer=profile.get('image', {}).get('footer', 'Concept for discussion'))


def make_image(account, profile, p, plan, photo):
    prompt = image_prompt(profile, p, plan)
    raw = llm.Stage('image', account['id']).image(prompt, shrink(photo, 1536) if photo else None)
    return to_jpeg(raw, 1280, 76), prompt


# ---------- image utilities (macOS sips; elsewhere images pass through unchanged) ----------
def _sips(raw, args, suffix):
    if not raw or not shutil.which('sips'):
        return None
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / ('in' + _ext(raw)), Path(d) / ('out' + suffix)
        src.write_bytes(raw)
        try:
            subprocess.run(['sips'] + args + [str(src), '--out', str(dst)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            return dst.read_bytes()
        except Exception:
            return None


def _ext(raw):
    return '.png' if raw[:8] == b'\x89PNG\r\n\x1a\n' else '.webp' if raw[:4] == b'RIFF' else '.jpg'


def shrink(raw, max_px):
    """Small reference photos: 512px for the writer's eyes (~85-350 tokens), 1536px for image editing."""
    if not raw:
        return raw
    return _sips(raw, ['-s', 'format', 'jpeg', '-s', 'formatOptions', '82', '-Z', str(max_px)], '.jpg') or raw


def to_jpeg(raw, max_px=1600, quality=85, keep_below=300000):
    """E-mail friendly ~150-250 KB JPEG instead of a 2-3 MB PNG (smaller mails = mailbox fills much more slowly)."""
    if raw[:3] == b'\xff\xd8\xff' and len(raw) < keep_below:
        return raw
    return _sips(raw, ['-s', 'format', 'jpeg', '-s', 'formatOptions', str(quality), '-Z', str(max_px)], '.jpg') or raw
