"""Conservative ownership scopes for explicitly printed PDF WhatsApp links.

Only extract_pdf_geometry needs pdfplumber. The scope parser is pure Python and
does not fetch URLs, infer accounts or invent WhatsApp links. PDF coordinates
are normalized to a top-left origin before any ownership comparisons.
"""
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit


EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
WA = re.compile(r"\bwhats\s*app\b", re.I)
SHARED = re.compile(
    r"customer\s*(?:support|service|care)|help\s*desk|helpline|hotline|"
    r"general\s*(?:enquir|inquir)|(?:sales|support)\s+team|switchboard|"
    r"reception|head\s+office|company\s+whatsapp|shared\s+(?:number|phone)|"
    r"order\s*(?:support|enquir)|客服|总机|service\s+client", re.I)
SHARED_EMAIL = re.compile(r"^(?:info|contact|sales|support|hello|office|admin|enquiries|inquiries|customerservice)$", re.I)
PHONE = re.compile(
    r"(?:(?:tel(?:ephone)?|phone|mobile|cell(?:phone)?|mob|whats\s*app)\s*[:.]?\s*)?"
    r"((?:\+|00)\d[\d\s().\-–]{6,28}\d)\s*", re.I)


def extract_pdf_geometry(path, page_numbers=None, max_pages=40):
    """Read selected 1-based pages, bounded by the first max_pages pages.

    The lazy import allows the application to call this in its bundled PDF
    runtime and pass the resulting JSON to its normal runtime.
    """
    import pdfplumber
    wanted = None if page_numbers is None else {int(n) for n in page_numbers if int(n) > 0}
    pages = []
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages[:max(0, int(max_pages))], 1):
            if wanted is not None and index not in wanted:
                continue
            words = [{key: word[key] for key in ('text', 'x0', 'x1', 'top', 'bottom')}
                     for word in page.extract_words(x_tolerance=2, y_tolerance=2)]
            links = []
            for annotation in page.annots or []:
                uri = annotation.get('uri')
                flags = int(annotation.get('data', {}).get('F', 0) or 0)
                # Invisible, Hidden and NoView annotation flags cannot establish
                # a visible contact button. No link destination is requested.
                if not uri or flags & (1 | 2 | 32):
                    continue
                if isinstance(uri, bytes):
                    uri = uri.decode('utf-8', errors='replace')
                links.append(dict(url=uri, **{key: float(annotation[key])
                                             for key in ('x0', 'x1', 'top', 'bottom')}))
            pages.append({'page': index, 'width': float(page.width),
                          'height': float(page.height), 'words': words, 'links': links})
    return pages


def _rect(item):
    return {key: float(item[key]) for key in ('x0', 'x1', 'top', 'bottom')}


def _overlap(word, link):
    """Require actual glyph overlap; touching a neighbouring label is not enough."""
    width = max(0, min(word['x1'], link['x1']) - max(word['x0'], link['x0']))
    height = max(0, min(word['bottom'], link['bottom']) - max(word['top'], link['top']))
    return (width >= .5 * max(1, word['x1'] - word['x0']) and
            height >= .5 * max(1, word['bottom'] - word['top']))


def _lines(words):
    """Group text baselines, splitting wide whitespace between adjacent cards."""
    rows = []
    for word in sorted(words, key=lambda w: (w['top'], w['x0'])):
        if not word.get('text', '').strip() or word['x1'] <= word['x0'] or word['bottom'] <= word['top']:
            continue
        row = next((r for r in reversed(rows[-4:])
                    if abs(r[0]['top'] - word['top']) <= 2), None)
        if row is None:
            rows.append([word])
        else:
            row.append(word)
    lines = []
    for row in rows:
        pieces = []
        for word in sorted(row, key=lambda w: w['x0']):
            gap = word['x0'] - pieces[-1][-1]['x1'] if pieces else 0
            if not pieces or gap > max(18, (word['bottom'] - word['top']) * 1.8):
                pieces.append([word])
            else:
                pieces[-1].append(word)
        for piece in pieces:
            lines.append({'text': ' '.join(w['text'] for w in piece), 'words': piece,
                          'x0': min(w['x0'] for w in piece), 'x1': max(w['x1'] for w in piece),
                          'top': min(w['top'] for w in piece), 'bottom': max(w['bottom'] for w in piece)})
    return sorted(lines, key=lambda line: (line['top'], line['x0']))


def _email(line):
    text = re.sub(r'^e-?mail\s*:\s*', '', line['text'], flags=re.I)
    compact = re.sub(r'\s+', '', text)
    return compact if EMAIL.fullmatch(compact) else ''


def _printed_phone(line):
    match = PHONE.fullmatch(line['text'].strip())
    if not match:
        return ''
    # A printed optional national trunk marker is not part of an international
    # number. Never infer a missing country code from the link or document URL.
    raw = re.sub(r'\(\s*0\s*\)', '', match[1])
    digits = re.sub(r'\D', '', raw)
    if raw.startswith('00'):
        digits = digits[2:]
    return '+' + digits if 8 <= len(digits) <= 15 and not digits.startswith('0') else ''


def _link_phone(url):
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.username or parsed.password:
        return None
    if parsed.scheme in ('http', 'https') and parsed.hostname == 'wa.me':
        value = unquote(parsed.path).strip('/')
    elif ((parsed.scheme in ('http', 'https') and parsed.hostname in ('api.whatsapp.com', 'web.whatsapp.com'))
          or parsed.scheme == 'whatsapp'):
        values = parse_qs(parsed.query).get('phone', [])
        value = values[0] if len(values) == 1 else ''
    else:
        return None
    value = value.strip().lstrip('+')
    return '+' + value if re.fullmatch(r'[1-9]\d{7,14}', value) else ''


def _same_column(line, anchor):
    return abs(line['x0'] - anchor['x0']) <= max(12, (anchor['bottom'] - anchor['top']) * 1.25)


def _addressee(label):
    tail = WA.split(label, maxsplit=1)[-1].strip(' :–-')
    tail = re.sub(r'^(?:with|to)\s+', '', tail, flags=re.I)
    if re.fullmatch(r"[A-ZÀ-ÖØ-Þ][\w'’.-]*(?:\s+[A-ZÀ-ÖØ-Þ][\w'’.-]*){0,3}", tail):
        if tail.casefold() not in ('us', 'now', 'here', 'chat', 'business', 'number', 'contact', 'team'):
            return tail
    return ''


def pdf_whatsapp_scopes(pages, source):
    """Return compatible accepted/rejected scopes from visible PDF geometry.

    Accepted scopes deliberately have names=[]: a verified email on this
    independently read document must link the scope to a known full name.
    The caller must also compare published_addressee (when present) to that
    verified name. The module never claims an account is registered or active.
    """
    scopes = []
    for ordinal, page in enumerate(pages[:40], 1):
        lines = _lines(page.get('words', []))
        email_lines = [line for line in lines if _email(line)]
        for link in page.get('links', []):
            number = _link_phone(link.get('url', ''))
            if number is None:
                continue
            channel = {'phone': number, 'url': link['url'], 'source': source,
                       'status': '公开 PDF 明示 WhatsApp；未验证账号',
                       'evidence_kind': 'pdf_person_label_link', 'page': page.get('page', ordinal)}
            scope = {'text': '', 'names': [], 'channels': [channel], 'excluded_reason': '',
                     'published_addressee': '', 'scope_email': '',
                     'pdf_evidence': {'page': page.get('page', ordinal), 'annotation': _rect(link)}}
            scopes.append(scope)

            def reject(reason):
                scope['excluded_reason'] = reason

            if not number:
                reject('WhatsApp 链接未明确发布有效国际号码'); continue
            if link['x1'] - link['x0'] > min(280, page['width'] * .6) or link['bottom'] - link['top'] > 48:
                reject('PDF 链接矩形跨越过大区域，归属不明确'); continue
            labels = []
            for line in lines:
                visible = ' '.join(w['text'] for w in line['words'] if _overlap(w, link))
                if WA.search(visible):
                    labels.append(line)
            if len(labels) != 1:
                reject('PDF 注释未与唯一可见 WhatsApp 文字标签相交'); continue
            label = labels[0]
            scope['text'] = label['text']
            scope['published_addressee'] = _addressee(label['text'])
            scope['pdf_evidence']['label'] = dict(text=label['text'], **_rect(label))
            if SHARED.search(label['text']) or re.search(r'\bshare\b|分享', label['text'], re.I):
                reject('WhatsApp 标签属于共享客服或分享渠道'); continue
            # A label may be indented to make room for an icon, but cannot
            # borrow an email from a different column or a distant contact.
            candidates = [line for line in email_lines
                          if -12 <= label['x0'] - line['x0'] <= 55
                          and abs(line['top'] - label['top']) <= 65]
            candidates.sort(key=lambda line: abs(line['top'] - label['top']))
            if not candidates:
                reject('WhatsApp 标签附近无同列独立邮箱条目'); continue
            email_line = candidates[0]
            if (len(candidates) > 1 and
                    abs(abs(candidates[1]['top'] - label['top']) - abs(email_line['top'] - label['top'])) < 4):
                reject('相邻邮箱条目距离相同，无法确定联系人'); continue
            address = _email(email_line)
            if SHARED_EMAIL.fullmatch(address.split('@', 1)[0]):
                reject('邮箱条目属于共享公司渠道'); continue
            phones = [line for line in lines if _printed_phone(line) and _same_column(line, email_line)
                      and abs(line['top'] - email_line['top']) <= 42
                      and abs(line['top'] - label['top']) <= 80]
            phones.sort(key=lambda line: abs(line['top'] - email_line['top']))
            if not phones:
                reject('邮箱条目附近没有独立印刷国际手机号'); continue
            phone_line = phones[0]
            if (len(phones) > 1 and _printed_phone(phones[1]) != _printed_phone(phone_line) and
                    abs(abs(phones[1]['top'] - email_line['top']) - abs(phone_line['top'] - email_line['top'])) < 4):
                reject('同列多个号码距离相同，归属不明确'); continue
            if _printed_phone(phone_line) != number:
                reject('WhatsApp URI 与最近联系人条目印刷号码不一致'); continue
            selected = [phone_line, email_line, label]
            top = min(line['top'] for line in selected)
            bottom = max(line['bottom'] for line in selected)
            between = [line for line in lines if _same_column(line, email_line)
                       and line['top'] >= top - 1 and line['bottom'] <= bottom + 1]
            if any(line not in selected for line in between):
                reject('邮箱、号码与 WhatsApp 之间存在其他联系人或正文条目'); continue
            headers = [line for line in lines if _same_column(line, email_line)
                       and 0 <= top - line['bottom'] <= 32]
            # Stop at a previous contact's fields; never absorb the preceding
            # person's email/phone into an otherwise valid compact card.
            headers = sorted(headers, key=lambda line: line['top'], reverse=True)
            prefix = []
            for header in headers[:2]:
                if _email(header) or _printed_phone(header) or WA.search(header['text']):
                    break
                prefix.append(header)
            context = sorted(prefix + selected, key=lambda line: (line['top'], line['x0']))
            text = '\n'.join(line['text'] for line in context)
            if SHARED.search(text):
                reject('联系人区域明确标记为客服或共享渠道'); continue
            scope['text'] = text
            scope['scope_email'] = address
            # Keep the normalized standalone email readable by the existing
            # email-verification gate without altering the source quotation.
            if address not in text:
                scope['text'] += '\n' + address
            scope['pdf_evidence'].update(
                email=dict(text=email_line['text'], normalized=address, **_rect(email_line)),
                printed_phone=dict(text=phone_line['text'], normalized=number, **_rect(phone_line)))
            channel.update(phone_raw=phone_line['text'], published_text=label['text'])
    # The text and encompassing button may be duplicate annotations. Keep one
    # accepted scope per channel/contact/label, preferring the tighter geometry.
    unique = {}
    rejected = []
    for scope in scopes:
        if scope['excluded_reason']:
            rejected.append(scope); continue
        key = (scope['channels'][0]['url'], scope['scope_email'], scope['pdf_evidence']['page'], scope['published_addressee'])
        rect = scope['pdf_evidence']['annotation']
        area = (rect['x1'] - rect['x0']) * (rect['bottom'] - rect['top'])
        old = unique.get(key)
        if old is None or area < old[0]:
            unique[key] = (area, scope)
    return [scope for _, scope in unique.values()] + rejected


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--pages', help='Comma-separated 1-based page numbers')
    args = parser.parse_args()
    print(json.dumps(extract_pdf_geometry(args.path, [int(n) for n in args.pages.split(',')] if args.pages else None)))
