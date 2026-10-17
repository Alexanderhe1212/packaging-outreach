"""官网抓取（零 token）：公开邮箱、主推产品、产品图、价格都直接从客户官网读取，不交给大模型。

顺序：Shopify /products.json → JSON-LD Product → 商品页 og 标签 → 首页 og:image。
邮箱：首页 → 联系/关于/Impressum 等页面；只采用官网上真实出现的地址。
"""
import html as htmllib
import json
from concurrent.futures import ThreadPoolExecutor
import random
import re
import ssl
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit
from .fetch_guard import DeferredFetch, FetchGuard

def _load_fetch_state():
    from . import store
    return store.get('public_fetch_guard_v1', {})

def _save_fetch_state(state):
    from . import store
    store.put('public_fetch_guard_v1', state)

FETCH_GUARD = FetchGuard(_load_fetch_state, _save_fetch_state)

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/129.0 Safari/537.36')
EMAIL_RE = re.compile(r'(?<![A-Z0-9._%+-])[A-Z0-9._%+-]{1,64}@[A-Z0-9.-]{1,253}\.[A-Z]{2,24}(?![A-Z0-9-])', re.I)
FREEMAIL = {'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'hotmail.co.uk', 'yahoo.com', 'yahoo.co.uk',
            'icloud.com', 'me.com', 'aol.com', 'proton.me', 'protonmail.com', 'gmx.de', 'gmx.net', 'web.de', 'live.com',
            'live.co.uk', 'btinternet.com', 'qq.com', '163.com', '126.com', 'yandex.com', 'mail.com', 'orange.fr', 'free.fr'}
SKIP_EMAIL = re.compile(r'(?i)(noreply|no-reply|donotreply|example\.|sentry|wixpress|@2x|\.(png|jpe?g|webp|gif|svg|css|js)$|'
                        r'^(privacy|gdpr|dpo|abuse|webmaster|careers|jobs|recruit|press|media|legal|accessibility|unsubscribe)@|'
                        r'@(sentry|shopify|myshopify|squarespace|wix|godaddy|domain|email|yourdomain|company)\.)')
GOOD_PREFIX = ('hello', 'info', 'contact', 'sales', 'wholesale', 'enquiries', 'inquiries', 'enquiry', 'team', 'office',
               'shop', 'studio', 'hi', 'mail', 'business', 'partnerships', 'trade', 'b2b', 'kontakt', 'bonjour')
OK_PREFIX = ('support', 'care', 'customercare', 'customerservice', 'service', 'help', 'admin', 'store')
CONTACT_HINT = re.compile(r'(?i)contact|kontakt|impressum|imprint|about|our-story|legal|faq|wholesale|stockist|trade|customer-?service|help')
TLD_COUNTRY = {'uk': 'United Kingdom', 'de': 'Germany', 'fr': 'France', 'nl': 'Netherlands', 'ie': 'Ireland', 'au': 'Australia',
               'nz': 'New Zealand', 'ca': 'Canada', 'se': 'Sweden', 'dk': 'Denmark', 'no': 'Norway', 'fi': 'Finland', 'ch': 'Switzerland',
               'at': 'Austria', 'be': 'Belgium', 'it': 'Italy', 'es': 'Spain', 'ae': 'UAE', 'sg': 'Singapore', 'us': 'USA', 'jp': 'Japan'}


class CrawlError(ValueError):
    pass


# ---------------- fetching ----------------
def _get_once(url, accept='text/html,application/xhtml+xml,*/*;q=0.8', max_bytes=4 * 1024 * 1024, timeout=12):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': accept, 'Accept-Language': 'en;q=0.9,*;q=0.5'})
    try:
        r = urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, 'reason', None), ssl.SSLError):
            raise
        # Read-only public page; some small-business sites ship broken certificate chains.
        r = urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context())
    with r:
        raw = r.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise CrawlError('response too large')
        return raw, r.geturl(), r.headers.get('Content-Type', '')


def page(url):
    raw, final, ctype = get(url)
    m = re.search(r'charset=([\w-]+)', ctype or '')
    return raw.decode(m.group(1) if m else 'utf-8', 'replace'), final


def host(url):
    h = (urlsplit(url if '//' in url else 'https://' + url).hostname or '').lower()
    return h[4:] if h.startswith('www.') else h


def root_domain(h):
    parts = (h or '').lower().split('.')
    if len(parts) >= 3 and parts[-2] in ('co', 'com', 'org', 'net', 'ac', 'gov') and len(parts[-1]) == 2:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:])


def normalize(url):
    url = (url or '').strip()
    if not url:
        raise CrawlError('没有网址')
    if '//' not in url:
        url = 'https://' + url
    u = urlsplit(url)
    return '%s://%s/' % (u.scheme or 'https', u.netloc)


def strip_tags(s):
    s = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', s or '')
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', htmllib.unescape(s)).strip()


def meta(doc, *names):
    for n in names:
        for pat in (r'<meta[^>]+(?:property|name|itemprop)=["\']%s["\'][^>]*content=["\']([^"\']*)' % re.escape(n),
                    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name|itemprop)=["\']%s["\']' % re.escape(n)):
            m = re.search(pat, doc, re.I)
            if m and m.group(1).strip():
                return htmllib.unescape(m.group(1).strip())
    return ''


# ---------------- emails ----------------
def emails_in(doc):
    text = htmllib.unescape(doc or '')
    # Collapse runs once before patterns with leading whitespace. Otherwise a
    # long run without an obfuscated address causes quadratic backtracking and
    # holds the GIL, starving both account workers and the HTTP server.
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s*(\[at\]|\(at\)|\{at\}|&#64;| at )\s*', '@', text, flags=re.I)
    text = re.sub(r'\s*(\[dot\]|\(dot\))\s*', '.', text, flags=re.I)
    text = text.replace('%40', '@')
    out = []
    for e in EMAIL_RE.findall(text):
        if len(e) > 254:
            continue
        e = e.lower().strip('.').lstrip('/')
        if e.startswith('u003e') or e.startswith('mailto:'):
            e = e.split(':')[-1].replace('u003e', '')
        if not SKIP_EMAIL.search(e) and e not in out:
            out.append(e)
    return out


def brand_tokens(site_root, brand=''):
    words = re.split(r'[^a-z0-9]+', (site_root.split('.')[0] + ' ' + brand).lower())
    return {w for w in words if len(w) >= 4}


def score_email(e, site_root, brand=''):
    if SKIP_EMAIL.search(e) or re.match(r'(?i)^(orders?|returns?|refunds?|complaints?|support|care|customercare|customerservice|help|service|shipping|tracking)@', e):
        return -1
    local, domain = e.split('@', 1)
    if root_domain(domain) == site_root:
        s = 10
    elif domain in FREEMAIL and any(t in local for t in brand_tokens(site_root, brand)):
        s = 2  # e.g. emberoakcandles@gmail.com; a private-looking freemail address is not used
    else:
        return -1  # agency, platform or unrelated company address
    if local.startswith(GOOD_PREFIX):
        s += 5
    elif local.startswith(OK_PREFIX):
        s += 3
    return s


def best_email(found, site_root, brand=''):
    ranked = sorted(((score_email(e, site_root, brand), e) for e in found), reverse=True)
    return ranked[0][1] if ranked and ranked[0][0] > 0 else ''


def contact_links(doc, base):
    links = []
    for href, label in re.findall(r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', doc, re.I | re.S)[:600]:
        if href.startswith(('mailto:', 'tel:', 'javascript:')):
            continue
        if CONTACT_HINT.search(href) or CONTACT_HINT.search(strip_tags(label)[:40]):
            u = urljoin(base, href)
            if host(u) == host(base) and u not in links:
                links.append(u)
    for path in ('/pages/contact', '/contact', '/contact-us', '/pages/contact-us', '/impressum', '/pages/about', '/about'):
        u = urljoin(base, path)
        if u not in links:
            links.append(u)
    return links


def business_emails(doc):
    """Only visible public contacts; reject conflicting mailto labels and restricted inbox context."""
    doc = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', doc or '')
    # Decode public Cloudflare email spans; this is published text, not a guessed address.
    def decode_public(match):
        try:
            raw = bytes.fromhex(match.group(2))
            email = bytes(b ^ raw[0] for b in raw[1:]).decode('utf-8')
            return match.group(0) + htmllib.escape(email) if EMAIL_RE.fullmatch(email) else match.group(0)
        except (ValueError, IndexError, UnicodeDecodeError):
            return match.group(0)
    doc = re.sub(r"(?i)<[^>]+data-cfemail=([\"'])([a-f0-9]+)\1[^>]*>", decode_public, doc)
    # Discard only the contradictory occurrence, not independent valid evidence elsewhere.
    def clear_conflict(match):
        href = htmllib.unescape(match.group(1)).strip()
        displayed = EMAIL_RE.findall(strip_tags(match.group(2)))
        return ' ' if displayed and any(e.lower() != href.lower() for e in displayed) else match.group(0)
    doc = re.sub(r"<a[^>]+href=[\"']mailto:([^\"'?]+)[^\"']*[\"'][^>]*>(.*?)</a>", clear_conflict, doc, flags=re.I | re.S)
    found = []
    # Context is local to a contact block. A returns section elsewhere must not
    # invalidate a separately published general or trade enquiry address.
    for block in re.split(r'(?i)</?(?:p|div|li|section|footer|br|h[1-6])\b[^>]*>', doc):
        text = strip_tags(block)
        bad = set()
        for match in EMAIL_RE.finditer(text):
            context = text[max(0, match.start()-95):match.end()+50]
            if re.search(r'(?i)(order (?:enquir|inquir|quer|status)|returns? (?:and|or|only)|refund|complaint|existing orders?)', context):
                if not re.search(r'(?i)(all|general|business|wholesale|partnership) (?:enquir|inquir|contact)', context):
                    bad.add(match.group().lower())
        found.extend(e for e in emails_in(block) if e not in bad and e not in found)
    return found


def verify_email(email, source, site, brand=''):
    """Re-read official evidence; neither a supplied email nor an AI assertion is evidence."""
    email = (email or '').strip().lower()
    if not EMAIL_RE.fullmatch(email or '') or root_domain(host(source)) != root_domain(host(site)):
        raise CrawlError('邮箱必须有同品牌官网公开来源')
    doc, final = page(source)
    if root_domain(host(final)) != root_domain(host(site)) or email not in business_emails(doc) or score_email(email, root_domain(host(site)), brand) <= 0:
        raise CrawlError('邮箱来源未验证或仅用于订单/售后')
    return final


def find_email(doc, base, brand='', limit=5, email_hint=''):
    email_hint = (email_hint or '').strip().lower()
    site_root = root_domain(host(base))
    def choose(d):
        found = business_emails(d)
        return best_email([email_hint] if email_hint and email_hint in found else ([] if email_hint else found), site_root, brand)
    email = choose(doc)
    if email and root_domain(email.split('@')[1]) == site_root:
        return email, base

    transient_errors = []
    def look(u):
        try:
            d, final = page(u)
            return (choose(d) if root_domain(host(final)) == site_root else ''), final
        except Exception as exc:
            transient = transient_failure(exc)
            if transient: transient_errors.append(transient)
            return '', u

    fallback = (email, base) if email else ('', '')
    with ThreadPoolExecutor(limit) as ex:  # contact pages in parallel: ~1 round trip instead of 5
        for e, final in ex.map(look, contact_links(doc, base)[:limit]):
            if e and root_domain(e.split('@')[1]) == site_root:
                return e, final
            if e and not fallback[0]:
                fallback = (e, final)
    if not fallback[0] and transient_errors:
        raise CrawlError("联系页临时不可读取，延后核实") from transient_errors[0]
    return fallback


# ---------------- products ----------------
SKIP_PRODUCT = re.compile(r'(?i)gift[ -]?card|e[ -]?gift|voucher|digital download|online course|tickets?|workshop|tour experience|shipping protection|insurance|donation|deposit')
SUPPLIER = re.compile(r'(?i)(?:packaging|rigid boxes?|paper bags?|mailer boxes?)\s+(?:manufacturer|supplier|wholesaler)|custom packaging solutions|packaging for your business')
NON_PRODUCT_PATH = re.compile(r'(?i)/(?:blogs?|news|careers?|jobs?|press)/')

def valid_product(p, base):
    return bool(p and p.get('name') and p.get('url') and p.get('image_url')
                and root_domain(host(p['url'])) == root_domain(host(base))
                and not NON_PRODUCT_PATH.search(p['url'])
                and not SKIP_PRODUCT.search(p['name'] + ' ' + p['url'])
                and not SUPPLIER.search(p['name']))


def _price(v):
    try:
        return float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return 0.0


def shopify_product(base):
    try:
        raw, _, ctype = get(urljoin(base, '/products.json?limit=60'), accept='application/json', timeout=15)
        data = json.loads(raw.decode('utf-8', 'replace'))
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get('products'), list):
        return None
    items = []
    for p in data.get('products', []):
        if not isinstance(p, dict):
            continue
        if not p.get('images') or SKIP_PRODUCT.search(p.get('title', '')) or SKIP_PRODUCT.search(p.get('product_type') or ''):
            continue
        variants = p.get('variants') or [{}]
        price = max((_price(v.get('price')) for v in variants if isinstance(v,dict)),default=0)
        items.append((price, p))
    if not items:
        return None
    items.sort(key=lambda x: -x[0])
    # Premium, giftable SKUs make better concepts; pick among the top few so reruns differ.
    price, p = random.choice(items[:3])
    facts = []
    if p.get('product_type'):
        facts.append(p['product_type'])
    opts = [o for o in (p.get('options') or []) if o.get('name', '').lower() not in ('title',) and o.get('values')]
    for o in opts[:2]:
        facts.append('%s: %s' % (o['name'], ', '.join(map(str, o['values'][:4]))))
    desc = strip_tags(p.get('body_html'))[:320]
    return {'name': p.get('title', ''), 'url': urljoin(base, '/products/' + p.get('handle', '')),
            'image_url': urljoin(base, p['images'][0].get('src', '')), 'price': ('%.2f' % price) if price else '',
            'facts': facts, 'description': desc, 'source': 'shopify'}


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def jsonld_product(doc, base):
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', doc, re.I | re.S):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for node in _walk(data):
            t = node.get('@type')
            if t == 'Product' or (isinstance(t, list) and 'Product' in t):
                if SKIP_PRODUCT.search(str(node.get('name', ''))):
                    continue
                img = node.get('image')
                if isinstance(img, list):
                    img = img[0] if img else ''
                if isinstance(img, dict):
                    img = img.get('url', '')
                offers = node.get('offers') or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = offers.get('price') or offers.get('lowPrice') or ''
                return {'name': htmllib.unescape(str(node.get('name', ''))), 'url': urljoin(base, str(node.get('url') or base)),
                        'image_url': urljoin(base, str(img or '')) if img else '',
                        'price': ('%s %s' % (price, offers.get('priceCurrency', ''))).strip() if price else '',
                        'facts': [], 'description': strip_tags(str(node.get('description', '')))[:320], 'source': 'jsonld'}
    return None


def product_from_links(doc, base):
    links = re.findall(r'href=["\']([^"\']*/(?:products?|shop|item|p)/[^"\'?#]+)', doc, re.I)
    # BigCommerce uses flat product URLs; card headings identify candidates,
    # while the fetched product page must still pass the existing product checks.
    cards = re.findall(r'<h[1-6][^>]*class=["\'][^"\']*card-title[^"\']*["\'][^>]*>(.*?)</h[1-6]>', doc, re.I | re.S)
    for card in cards:
        links.extend(re.findall(r'href=["\']([^"\'?#]+)', card, re.I))
    seen = []
    for href in links:
        u = urljoin(base, href)
        if host(u) == host(base) and u not in seen and not SKIP_PRODUCT.search(u):
            seen.append(u)
    for u in seen[:2]:
        try:
            d, final = page(u)
        except Exception:
            continue
        p = jsonld_product(d, final)
        if valid_product(p, base):
            return p
        title = meta(d, 'og:title') or (re.search(r'<title>(.*?)</title>', d, re.I | re.S) or [None, ''])[1]
        img = meta(d, 'og:image', 'og:image:secure_url')
        if title and img and not SKIP_PRODUCT.search(title) and root_domain(host(final)) == root_domain(host(base)) and (meta(d, 'og:type') == 'product' or meta(d, 'product:price:amount', 'og:price:amount')):
            price = meta(d, 'product:price:amount', 'og:price:amount')
            return {'name': strip_tags(title)[:120], 'url': final, 'image_url': urljoin(final, img),
                    'price': ('%s %s' % (price, meta(d, 'product:price:currency', 'og:price:currency'))).strip() if price else '',
                    'facts': [], 'description': meta(d, 'og:description', 'description')[:320], 'source': 'og'}
    return None


def brand_name(doc, base):
    name = meta(doc, 'og:site_name', 'application-name', 'apple-mobile-web-app-title')
    if not name:
        t = re.search(r'<title[^>]*>(.*?)</title>', doc, re.I | re.S)
        name = strip_tags(t.group(1)) if t else ''
        name = re.split(r'\s+[|\-–—:·]\s+', name)[0] if name else ''
    if not name or len(name) > 60:
        name = host(base).split('.')[0].replace('-', ' ').title()
    return name.strip()


def crawl(url, email_hint='', email_sources=None):
    """Return a prospect dict built only from the company's own public pages. Raises CrawlError with a short reason."""
    base = normalize(url)
    try:
        doc, final = page(base)
    except Exception as e:
        raise CrawlError('打不开官网（%s）' % web_error_label(e)) from e
    base = normalize(final)
    if re.search(r'(?i)domain (is )?for sale|buy this domain|parked free|coming soon</title>', doc[:20000]):
        raise CrawlError('域名停放或未上线')
    brand = brand_name(doc, base)
    description = meta(doc, 'og:description', 'description') or ''
    if SUPPLIER.search(brand + ' ' + description):
        raise CrawlError('包装同行供应商，不是目标品牌')
    def select_product():
        requested = url if '://' in url else 'https://' + url
        if urlsplit(requested).path.strip('/'):
            product_doc, product_final = page(requested)
            product = jsonld_product(product_doc, product_final)
            if not valid_product(product, base):
                raise CrawlError('指定产品未核实，不自动换成其他商品')
            return product
        return shopify_product(base) or jsonld_product(doc, base) or product_from_links(doc, base)

    try:
        email, source = '', ''
        # Saved evidence is a navigation hint only: re-read it with the normal verifier.
        for candidate in (email_sources or [])[:3]:
            if not isinstance(candidate, str) or root_domain(host(candidate)) != root_domain(host(base)):
                continue
            try:
                hint = email_hint.lower().strip()
                if not hint:
                    evidence, evidence_url = page(candidate)
                    if root_domain(host(evidence_url)) != root_domain(host(base)):
                        continue
                    hint = best_email(business_emails(evidence), root_domain(host(base)), brand)
                source = verify_email(hint, candidate, base, brand)
                email = hint
                break
            except Exception as exc:
                if transient_failure(exc):
                    raise CrawlError('已保存的邮箱来源暂不可读取，延后核实') from exc
        if not email:
            email, source = find_email(doc, base, brand, email_hint=email_hint.lower().strip())
        if not email:
            raise CrawlError('官网没有可验证的通用或商务邮箱')
        product = select_product()
    except CrawlError:
        raise
    except Exception as e:
        raise CrawlError('产品或联系页面暂不可核实（%s）' % web_error_label(e)) from e
    if not valid_product(product, base):
        raise CrawlError('官网没有可验证的具体实体产品')
    tld = host(base).rsplit('.', 1)[-1]
    p = {
        'company': brand, 'customer_brand': brand, 'website': base, 'domain': host(base),
        'email': email, 'email_source': source, 'email_verified': True,
        'match_reason': '官网实体产品 %s 可评估精品硬盒、手提袋或快递盒方案；适配推测，非采购确认' % product['name'],
        'purchase_signal': 'fit_inference', 'purchase_signal_source': '', 'product_source': product['url'],
        'country': TLD_COUNTRY.get(tld, ''), 'lang': (re.search(r'<html[^>]+lang=["\']([\w-]+)', doc, re.I) or [None, ''])[1][:5],
        'site_description': (meta(doc, 'og:description', 'description') or '')[:300],
        'product_name': '', 'product_url': '', 'product_image_url': meta(doc, 'og:image', 'og:image:secure_url'),
        'product_facts': [], 'product_price': '', 'product_description': '',
    }
    if p['product_image_url']:
        p['product_image_url'] = urljoin(base, p['product_image_url'])
    if product:
        p.update(product_name=product['name'], product_url=product['url'], product_facts=product['facts'],
                 product_price=product['price'], product_description=product['description'])
        if product.get('image_url'):
            p['product_image_url'] = product['image_url']
    return p


# ---------------- images ----------------
def is_image(raw):
    return raw[:8] == b'\x89PNG\r\n\x1a\n' or raw[:3] == b'\xff\xd8\xff' or (raw[:4] == b'RIFF' and raw[8:12] == b'WEBP')


def product_image(image_url, page_url=None):
    """Download the real product photo (fallback: the page's og:image). Shopify CDN images are requested at 1200px."""
    def og_of_page():
        try:
            d, final = page(page_url)
            og = meta(d, 'og:image', 'og:image:secure_url')
            return urljoin(final, og) if og else None
        except Exception:
            return None

    for u in (image_url, 'PAGE' if page_url else None):
        if u == 'PAGE':
            u = og_of_page()
        if not u:
            continue
        if u.startswith('//'):
            u = 'https:' + u
        if 'cdn.shopify.com' in u or '/cdn/shop/' in u:
            u += ('&' if '?' in u else '?') + 'width=1200'
        try:
            raw, _, _ = get(u, accept='image/webp,image/png,image/jpeg,*/*;q=0.5', max_bytes=15 * 1024 * 1024)
            if is_image(raw) and len(raw) > 6000:
                return raw, u
        except Exception:
            continue
    return None, None


# Read-only public fetch retries. No SMTP code calls these functions.
def transient_failure(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, DeferredFetch): return exc
        if isinstance(exc, urllib.error.HTTPError):
            if exc.code in (408, 429, 500, 502, 503, 504): return exc
        elif isinstance(exc, (TimeoutError, ConnectionError)):
            return exc
        elif isinstance(exc, urllib.error.URLError):
            # Certificate, permission and DNS-not-found failures are not retried here.
            reason = getattr(exc, 'reason', None)
            if isinstance(reason, (TimeoutError, ConnectionError)): return exc
        exc = exc.__cause__ or exc.__context__
    return None


def retry_after(exc):
    import time
    from email.utils import parsedate_to_datetime
    if getattr(exc, 'retry_at', None):
        return max(0., exc.retry_at-time.time())
    raw = getattr(exc, 'headers', {}).get('Retry-After', '') if getattr(exc, 'headers', None) else ''
    try: return max(0., float(raw))
    except (ValueError, TypeError):
        try: return max(0., parsedate_to_datetime(raw).timestamp()-time.time())
        except (ValueError, TypeError, OverflowError): return 0.


def web_error_label(exc):
    if isinstance(exc, DeferredFetch):
        return '限流等待，未发起新请求'
    if isinstance(exc, urllib.error.HTTPError):
        return 'HTTP %s%s' % (exc.code, ' 临时错误，等待重试' if transient_failure(exc) else '，需核实来源')
    return type(exc).__name__


def get(url, accept='text/html,application/xhtml+xml,*/*;q=0.8', max_bytes=4*1024*1024, timeout=12):
    domain = root_domain(host(url))
    with FETCH_GUARD.request(domain):
        try:
            result = _get_once(url, accept, max_bytes, timeout)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            transient = transient_failure(exc)
            if transient:
                transient.retry_at = FETCH_GUARD.failed(domain, getattr(transient, 'code', None), retry_after(transient))
            raise
        FETCH_GUARD.succeeded(domain)
        return result
