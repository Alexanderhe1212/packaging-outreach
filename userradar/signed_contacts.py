"""Extract explicitly signed, first-person business contact invitations.

This deliberately does not join arbitrary neighbouring contact cards. Channels
come from the self-reference; a unique following signature supplies identity.
"""
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup
from contact_extract import NAME, EXCLUDE
from contact_quality import country_hint, phone_info, whatsapp_links

SELF = re.compile(r'\b(?:contact\s+me|reach\s+me|call\s+me|my\s+(?:mobile|phone|telephone|cell|e-?mail))\b', re.I)
SELF_PHONE = re.compile(
    r'\b(?:my\s+(?:mobile(?:\s+(?:phone|number))?|phone|telephone|cell(?:phone)?)(?:\s+(?:is|on|at))?'
    r'|(?:contact|reach|call|text|message)\s+me\s+(?:on|at))\s*[:–—-]?\s*'
    r'((?:\+|00)?\d[\d\s().-]{5,25}\d)', re.I)
NUMBER = re.compile(r'(?<!\w)(?:\+|00)?\d[\d\s().-]{5,25}\d')
ROLE_MAILBOX = re.compile(r'^(?:c[efomti]o|ceo|founder|owner|president|director|managing[._-]?director)$', re.I)
SHARED = re.compile(r'customer\s*(?:support|service|care)|help\s*desk|helpline|general\s*(?:enquir|contact)|'
                    r'support\s*team|company\s*(?:phone|mobile|whatsapp)|office\s*whatsapp|客服|总机', re.I)
BAD_NAME = re.compile(r'whatsapp|phone|mobile|email|e-mail|office|voice|working hours|contact|send|request|business', re.I)
BLOCKED_MARKER = re.compile(r'(?:^|[\s_-])(?:footer|navbar|navigation|sidebar|comments|related|recommendations)(?:$|[\s_-])', re.I)


def _hidden_or_shared(node):
    for parent in [node] + list(node.parents):
        if parent.name in ('footer', 'nav', 'aside', 'form', 'script', 'style', 'noscript'):
            return True
        if parent.get('role') in ('contentinfo', 'navigation'):
            return True
        if parent.has_attr('hidden') or parent.get('aria-hidden') == 'true':
            return True
        if re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', parent.get('style', ''), re.I):
            return True
        # Body theme flags such as has-fixed-footer do not make all content a footer.
        if parent.name not in ('body', 'html', '[document]'):
            marker = ' '.join([parent.get('id', ''), ' '.join(parent.get('class', []))])
            if BLOCKED_MARKER.search(marker):
                return True
    return False


def _clean(soup):
    cleaned = BeautifulSoup(str(soup), 'html.parser')
    for node in list(cleaned.find_all(True)):
        if node.parent is not None and _hidden_or_shared(node):
            node.decompose()
    return cleaned


def _text(node):
    return node.get_text(' ', strip=True)


def _signature(node, role):
    text = node.get_text('\n', strip=True)
    if len(text) > 220:
        return None
    lines = [x.strip(' ,\t') for x in re.split(r'\n|\s+[—–|]\s+', text) if x.strip()]
    for index, name in enumerate(lines[:-1]):
        title = lines[index + 1]
        if (NAME.fullmatch(name) and not EXCLUDE.search(name) and not BAD_NAME.search(name)
                and not role.search(name) and role.search(title) and len(title) <= 120 and '@' not in title):
            return name, title
    return None


def _inside(node, ancestor):
    return node is ancestor or any(p is ancestor for p in node.parents)


def _email_values(node, emails):
    values = set(emails(_text(node)))
    for anchor in node.select('a[href]'):
        if anchor['href'].lower().startswith('mailto:'):
            values.update(emails(unquote(anchor['href'].split('?', 1)[0])))
    return {value.casefold() for value in values}


def _shared_channel(node, scope):
    for parent in [node] + list(node.parents):
        if parent is scope:
            break
        text = _text(parent)
        if len(text) <= 450 and SHARED.search(text) and not SELF.search(text):
            return True
    return False


def _self_email(node, address):
    text = _text(node)
    route = (r'(?:\b(?:contact|reach|e-?mail|write(?:\s+to)?)\s+me\s*(?:(?:on|at|via)\s*)?'
             r'|\bmy\s+e-?mail\s*(?:address\s*)?(?:is\s*)?'
             r'|\b(?:or|and)\s*(?:via\s*)?(?:e-?mail\s*)?)')
    if re.search(route + r'[:：]?\s*' + re.escape(address), text, re.I):
        return True
    return any(a.get('href', '').lower().startswith('mailto:' + address)
               and re.search(r'e-?mail', _text(a), re.I) for a in node.select('a[href]'))


def _channels(scope, source, number, region):
    """Accept an explicit publication only when its recipient is the self-number."""
    found = []
    for anchor in scope.select('a[href]'):
        if _shared_channel(anchor, scope):
            continue
        for channel in whatsapp_links(BeautifulSoup(str(anchor), 'html.parser'), source):
            if phone_info(channel['phone'], region)['phone_e164'] != number:
                continue
            context = anchor
            for parent in anchor.parents:
                if parent is scope or parent.name in ('p', 'tr', 'li', 'address'):
                    context = parent
                    break
                if len(_text(parent)) > 450:
                    break
                context = parent
            text = _text(context)
            if SHARED.search(text) or re.search(r'\bshare\b|分享', _text(anchor) + ' ' + anchor.get('aria-label', ''), re.I):
                continue
            found.append(dict(channel, evidence_kind='signed_person_link', ownership_quote=text))
    # Text-only "Voice & WhatsApp" is publication evidence, not an invented URL.
    for node in scope.find_all(['p', 'tr', 'li', 'address', 'div', 'span']):
        text = _text(node)
        if (len(text) > 350 or not re.search(r'\bwhats\s*app\b', text, re.I)
                or SHARED.search(text) or _shared_channel(node, scope)
                or re.search(r'\bshare\b|分享', text, re.I)):
            continue
        numbers = {phone_info(m.group(), region)['phone_e164'] for m in NUMBER.finditer(text)} - {''}
        if numbers != {number}:
            continue
        if any(_text(child) == text for child in node.find_all(['p', 'tr', 'li', 'address', 'div', 'span'])):
            continue
        found.append({'phone': number, 'url': '', 'source': source,
                      'status': '公开原文明示 WhatsApp；未验证账号',
                      'evidence_kind': 'signed_person_label', 'ownership_quote': text})
    # A published link and its label are the same channel, not two hits.
    if any(channel['url'] for channel in found):
        found = [channel for channel in found if channel['url']]
    return list({(channel['phone'], channel['url']): channel for channel in found}.values())


def signed_contacts(soup, url, role, emails, is_role):
    """Return people supported by one self-contact and one unique signature.

    ``email_kind=person_attributed_role_mailbox`` must remain distinct from a
    named work mailbox in downstream qualification. No domain/person constants.
    """
    region = country_hint(soup)
    clean = _clean(soup)
    tags = list(clean.find_all(True))
    positions = {id(node): index for index, node in enumerate(tags)}
    intros = []
    for node in clean.find_all(['p', 'div', 'address', 'blockquote']):
        if len(_text(node)) > 650 or not SELF.search(_text(node)):
            continue
        if any(SELF.search(_text(child)) for child in node.find_all(['p', 'div', 'address', 'blockquote'])):
            continue
        intros.append(node)
    signatures = []
    for node in clean.find_all(['p', 'div', 'small', 'address', 'figcaption', 'section', 'article']):
        value = _signature(node, role)
        if value and not any(_signature(child, role) == value for child in node.find_all(True)):
            signatures.append((node, value))
    found = []
    for intro in intros:
        text = _text(intro)
        if SHARED.search(text):
            continue
        addresses = _email_values(intro, emails)
        if len(addresses) != 1:
            continue
        address = next(iter(addresses))
        if not _self_email(intro, address):
            continue
        numbers = list(dict.fromkeys(match.group(1).strip() for match in SELF_PHONE.finditer(text)))
        if len(numbers) > 1:
            continue
        raw = numbers[0] if numbers else ''
        number = phone_info(raw, region)['phone_e164']
        for scope in intro.parents:
            if scope.name in ('body', 'html', '[document]'):
                break
            scope_text = _text(scope)
            if len(scope_text) > 1600:
                break
            candidates = [(node, value) for node, value in signatures if _inside(node, scope)]
            if not candidates:
                continue
            # Never connect two people or two self-references across a parent.
            if len(candidates) != 1 or sum(_inside(node, scope) for node in intros) != 1:
                break
            signature, (name, title) = candidates[0]
            if positions[id(signature)] <= positions[id(intro)]:
                break
            other_names = []
            for node in scope.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'strong', 'b']):
                value = _text(node)
                if (NAME.fullmatch(value) and not role.search(value) and not EXCLUDE.search(value)
                        and not BAD_NAME.search(value) and value != name):
                    other_names.append(value)
            if other_names:
                break
            extra = _email_values(scope, emails) - {address}
            if any(not is_role(value) and not ROLE_MAILBOX.fullmatch(value.split('@')[0]) for value in extra):
                break
            role_box = bool(ROLE_MAILBOX.fullmatch(address.split('@')[0]) or is_role(address))
            if is_role(address) and not ROLE_MAILBOX.fullmatch(address.split('@')[0]):
                break
            channels = _channels(scope, url, number, region) if number else []
            evidence = text + '\n' + name + '\n' + title
            for channel in channels:
                channel.update(attribution='person', attributed_name=name,
                               ownership_basis='第一人称指定号码与唯一具名署名；同号明确 WhatsApp 发布',
                               account_status='未验证账号当前有效性')
            found.append({'name': name, 'title': title, 'email': address,
                          'email_kind': 'person_attributed_role_mailbox' if role_box else 'named_work_email',
                          'person_designated_role_email': role_box,
                          'email_note': '本人明确指定的职务邮箱；未验证独享或投递' if role_box else '本人明确指定的工作邮箱；未验证投递',
                          'email_attribution': 'person', 'phone': raw, 'phone_raw': raw,
                          'country_hint': region, 'source': url, 'signed_contact': True,
                          'status': '官网第一人称联系方式与唯一署名明确关联；未验证投递或接通',
                          'evidence': evidence, 'explicit_whatsapp': channels,
                          'contact_phone_candidates': [raw] if raw else [],
                          'evidence_by_field': {
                              'identity': [{'url': url, 'quote': name + '\n' + title}],
                              'email': [{'url': url, 'quote': text}],
                              'phone': [{'url': url, 'quote': text}] if raw else [],
                              'whatsapp': [{'url': url, 'quote': channel['ownership_quote']} for channel in channels]}})
            break
    return list({(person['name'], person['email'], person['phone']): person for person in found}.values())
