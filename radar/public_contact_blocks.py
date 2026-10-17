"""Extract bounded, visible person blocks without inferring missing identities.

The caller may join full-name identity/contact observations on the same domain.
This module deliberately does not merge people, qualify leads, or infer WhatsApp.
"""
import re
from urllib.parse import unquote

from bs4 import NavigableString, Tag
from person_identity import plausible_person_name


_ATOMIC = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'dt', 'dd'}
_CONTAINERS = {'div', 'section', 'article', 'li', 'td', 'address', 'dl'}
_BLOCKS = _ATOMIC | _CONTAINERS | {'main', 'header', 'footer', 'nav', 'aside', 'form', 'ul', 'ol', 'table'}
_EXCLUDED = re.compile(r'(?:^|[\s_-])(?:recommend\w*|suggest\w*|related|comments?|social.share|share.button)(?:$|[\s_-])', re.I)
_NOT_NAME = re.compile(r'\b(?:contact|office|admin|customer|support|service|hours|opening|email|phone|mobile|whatsapp|team|department|sales|director|manager|officer|president|founder|owner|procurement|purchasing|shipping|privacy|terms|coffee|roastery|roasters|roasting|region|address|enquiries|inquiries|newsletter)\b', re.I)
_SHARED = re.compile(r'\b(?:admin(?:istration)?|office|customer|support|service|department|general|reception|enquiries|inquiries|contact us|opening hours|find us)\b', re.I)
_NUMBER = re.compile(r'^(?:(?:mobile|mob\.?|cell|tel(?:ephone)?\.?|phone|whats\s*app|wa)\s*[:：.]?\s*)?((?:\+|00)?\d[\d ().-]{5,28}\d)\s*$', re.I)
_PARTICLES = {'van', 'von', 'de', 'del', 'da', 'di', 'du', 'la', 'le'}
_OWNER_LIST = re.compile(r'\b(?P<role>(?:co[- ]?)?owners?|(?:co[- ]?)?founders?)\s*\((?P<names>[^()\n]{3,180})\)', re.I)
_HISTORICAL = re.compile(r'\b(?:former|previous|past|retired|not|never|no longer|used to be)\b|\bex[- ]', re.I)
_TITLE_PREFIX = re.compile(r'(?:(?:head|director|manager|chief|senior|junior|global|regional|group|executive|vice|president|vp|of|and|co)\s*[-/&]?\s*)*', re.I)


def _clean(text):
    return re.sub(r'\s+', ' ', text.replace('\u200b', ' ').replace('\ufeff', ' ')).strip()


def _blocked(node):
    for parent in [node, *node.parents]:
        if not isinstance(parent, Tag):
            continue
        if parent.name in {'script', 'style', 'noscript', 'svg', 'template', 'nav', 'aside', 'footer', 'form'}:
            return True
        if parent.has_attr('hidden') or parent.get('aria-hidden', '').lower() == 'true':
            return True
        if parent.get('role') in {'navigation', 'contentinfo'}:
            return True
        if re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', parent.get('style', ''), re.I):
            return True
        marker = ' '.join([str(parent.get('id', '')), ' '.join(parent.get('class', [])), str(parent.get('aria-label', ''))])
        if _EXCLUDED.search(marker):
            return True
    return False


def _full_name(text, role):
    """A full displayed name, never an email-local-part or a first-name guess."""
    text = _clean(text).rstrip(':：')
    if len(text) > 80 or _NOT_NAME.search(text) or role.search(text):
        return ''
    return text if plausible_person_name(text) else ''


def _lines(node):
    """Keep BR and paragraph boundaries, but keep inline spans on one line."""
    result, current = [], []

    def flush():
        value = _clean(' '.join(current))
        if value:
            result.append(value)
        current.clear()

    def walk(item):
        if isinstance(item, NavigableString):
            current.append(str(item))
            return
        if not isinstance(item, Tag) or _blocked(item):
            return
        if item.name == 'br':
            flush()
            return
        if item is not node and item.name in _BLOCKS:
            flush()
        for child in item.children:
            walk(child)
        if item.name == 'a':
            href = item.get('href', '')
            if href.lower().startswith(('mailto:', 'tel:')):
                target = unquote(href.split(':', 1)[1].split('?', 1)[0])
                if target and target not in item.get_text(' ', strip=True):
                    current.append(target)
        if item is not node and item.name in _BLOCKS:
            flush()

    walk(node)
    flush()
    return result


def _groups(soup):
    """Never flatten separate structural cards into a common ancestor's text."""
    for container in soup.find_all(list(_CONTAINERS)):
        if _blocked(container):
            continue
        group, inline = [], []

        def flush_inline():
            if inline:
                value = _clean(' '.join(inline))
                if value:
                    group.append(value)
                inline.clear()

        for child in container.children:
            if isinstance(child, NavigableString):
                if str(child).strip():
                    inline.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            if _blocked(child):
                flush_inline()
                group.append(None)
            elif child.name in _ATOMIC or (child.name == 'div' and not child.find(list(_BLOCKS))):
                flush_inline()
                group.extend(_lines(child))
            elif child.name in _BLOCKS:
                flush_inline()
                group.append(None)
            elif child.name == 'br':
                flush_inline()
            else:
                inline.extend(_lines(child))
        flush_inline()
        if group:
            yield group
    # A plain paragraph can itself contain an entire BR-separated card.
    for tag in soup.find_all(list(_ATOMIC)):
        if not _blocked(tag):
            lines = _lines(tag)
            if len(lines) > 1:
                yield lines


def _title(line, role):
    if len(line) > 120 or len(line.split()) > 12 or '@' in line or re.search(r'\d|[.!?;]', line) or _HISTORICAL.search(line):
        return ''
    match = role.search(line)
    if not match or not _TITLE_PREFIX.fullmatch(line[:match.start()].strip()):
        return ''
    return line


def _phone(line):
    # Emoji on an explicit contact line is decoration, not part of the number.
    line = re.sub(r'^[^\w+]+', '', line).strip()
    match = _NUMBER.fullmatch(line)
    if not match:
        return ''
    value = match[1].strip()
    return value if 7 <= len(re.sub(r'\D', '', value.replace('(0)', ''))) <= 15 else ''


def _email_line(line, emails):
    addresses = emails(line)
    if not addresses:
        return []
    remainder = line
    for address in addresses:
        remainder = remainder.replace(address, '')
    remainder = re.sub(r'\b(?:email|e-mail|mail|email me)\b', '', remainder, flags=re.I)
    # Sentences mentioning somebody else's address are not contact fields.
    return addresses if not re.search(r'\w', remainder) else []


def extract_public_blocks(soup, url, role, emails, is_role):
    """Return standard person dictionaries, including incomplete evidence clues.

    ``contact_only`` means no relevant title was explicitly published in that
    block. ``identity_only`` has a name/title but no attributed email or phone.
    Neither flag allows the caller to treat a missing field as verified.
    """
    found = []
    for lines in _groups(soup):
        for i, line in enumerate(lines):
            name = _full_name(line, role) if line else ''
            if not name:
                continue
            titles, addresses, numbers, evidence = [], [], [], [line]
            for following in lines[i + 1:i + 9]:
                if not following or _full_name(following, role) or _SHARED.search(following):
                    break
                title = _title(following, role)
                address = _email_line(following, emails)
                number = _phone(following)
                if not (title or address or number):
                    break
                evidence.append(following)
                if len('\n'.join(evidence)) > 650:
                    break
                if title:
                    titles.append(title)
                addresses.extend(address)
                if number:
                    numbers.append(number)
            addresses = list(dict.fromkeys(addresses))
            unique_numbers = {}
            for number in numbers:
                unique_numbers.setdefault(re.sub(r'\D', '', number.replace('(0)', '')), number)
            numbers = list(unique_numbers.values())
            title = titles[0] if len(set(titles)) == 1 else ''
            email = addresses[0] if len(addresses) == 1 and not is_role(addresses[0]) else ''
            phone = numbers[0] if len(numbers) == 1 else ''
            if not (title or email or numbers):
                continue
            record = {'name': name, 'title': title, 'email': email, 'phone': phone,
                      'phone_raw': phone, 'source': url,
                      'status': '官网局部联系人条目；缺失项不推测',
                      'evidence': '\n'.join(evidence), 'contact_phone_candidates': numbers,
                      'contact_only': not bool(title),
                      'identity_only': bool(title and not email and not numbers)}
            record['evidence_by_field'] = {
                field: [{'url': url, 'quote': record['evidence']}]
                for field in ('name', 'title', 'email', 'phone') if record[field]
            }
            found.append(record)

    # Only explicit ownership/founder lists; a nearby shared mailbox stays out.
    for tag in soup.find_all(['p', 'li']):
        if _blocked(tag):
            continue
        text = _clean(tag.get_text(' ', strip=True))
        if len(text) > 1200:
            continue
        for match in _OWNER_LIST.finditer(text):
            if _HISTORICAL.search(text[max(0, match.start() - 70):match.start()]):
                continue
            title = 'Founder' if 'founder' in match['role'].lower() else 'Owner'
            if not role.search(title):
                continue
            names = re.split(r'\s*(?:&|\band\b|,)\s*', match['names'])
            if not names or len(names) > 5 or any(not _full_name(n, role) for n in names):
                continue
            for name in names:
                quote = match.group(0)
                found.append({'name': _full_name(name, role), 'title': title,
                              'email': '', 'phone': '', 'source': url,
                              'status': '官网明确身份叙述；联系方式需独立归属证据',
                              'evidence': quote, 'identity_only': True,
                              'evidence_by_field': {field: [{'url': url, 'quote': quote}] for field in ('name', 'title')}})
    unique = {}
    for record in found:
        key = tuple(record.get(k, '') for k in ('name', 'title', 'email', 'phone', 'evidence'))
        unique.setdefault(key, record)
    return list(unique.values())
