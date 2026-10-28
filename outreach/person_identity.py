"""Conservative displayed-name screening, never an identity verification substitute.

The check only rejects obvious section/business labels and malformed names. A
passing name still needs independently read role and contact attribution proof.
No surname is inferred from a mailbox, first name, title or neighbouring card.
"""
import re

_PARTICLES = {'van', 'von', 'de', 'del', 'da', 'di', 'du', 'la', 'le', 'der', 'den', 'dos', 'das', 'al', 'bin', 'ibn'}
PRESS_MAILBOXES = frozenset({'press', 'presse', 'media', 'pressoffice', 'prensa', 'pressekontakt'})


def press_mailbox(address):
    return str(address or '').strip().partition('@')[0].casefold() in PRESS_MAILBOXES

# Public website section/navigation vocabulary seen misidentified as people.
# Do not include ordinary surnames such as Brown, Green, King, Rose or May.
_NON_PERSON = re.compile(
    r'\b(?:factory|factories|knowledge|products?|packaging|roastery|roasters|'
    r'roasting|exports?|imports?|manufacturing|manufacturers?|corporation|'
    r'company|companies|industries|industry|enterprise|enterprises|'
    r'contact|contacts|customer|customers|support|services?|department|'
    r'privacy|terms|newsletter|subscribe|website|welcome|navigation|'
    r'overview|history|mission|vision|quality|sustainability|certifications?|'
    r'buying|shopping|ordering|delivery|shipping|opening|visit|visitor|centre|center|showroom|warehouse|retail|shop|gallery|catalogue|catalog|news|blog|careers?|vacancies|'
    r'founder|owner|director|manager|procurement|purchasing|officer|'
    r'president|chairman|ceo|sales|team|teamet|office|admin|administration|'
    r'email|phone|mobile|whatsapp|address|enquiries|inquiries)\b', re.I)
_NON_PERSON_PHRASES = re.compile(
    r'^(?:follow\b|connect with\b|stay connected\b)|'
    r'^(?:kontakt\b|espace journalistes\b|sala de prensa\b|area stampa\b)|'
    r'\b(?:about us|our story|our people|meet us|tea knowledge|the first|the journey|glorious leader|'
    r'customizable treatment|flagship store|visits and tours|eigene edition)\b', re.I)


def plausible_person_name(value):
    """Return bool for a displayed full-name candidate; do not alter its value.

    Unicode letters, hyphens, apostrophes, initials and common lowercase name
    particles are supported. One-word names remain incomplete under the app's
    full-name requirement. Newlines remain structural boundaries, never joins.
    """
    if not isinstance(value, str) or '\n' in value or '\r' in value:
        return False
    text = re.sub(r'[ \t]+', ' ', value).strip()
    if not text or len(text) > 90 or _NON_PERSON.search(text) or _NON_PERSON_PHRASES.search(text):
        return False
    if re.fullmatch(r'(?:opening|office|business) hours|(?:corrugated|rigid|folding|display|shipping|custom|paper) (?:boxes|box|cartons|bags)', text, re.I):
        return False
    parts = text.split(' ')
    if parts and parts[0].rstrip('.').lower() in {'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'sir'}:
        parts = parts[1:]
    if not 2 <= len(parts) <= 7:
        return False
    proper = []
    for part in parts:
        if part in _PARTICLES:
            continue
        letters = part.replace('-', '').replace("'", '').replace('’', '').replace('.', '')
        if not letters.isalpha() or not letters[0].isupper():
            return False
        # Punctuation may connect letters or mark an initial, not create tokens.
        if not re.fullmatch(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*(?:\.)?", part, re.UNICODE):
            return False
        proper.append(letters)
    # All-initial sequences provide no full-name identity to resolve.
    return len(proper) >= 2 and any(len(part) > 1 for part in proper)


def explicit_short_name(name, email, quote):
    """A displayed first name needs its own exact name/role/email block."""
    if not isinstance(name, str) or len(name) < 2 or ' ' in name:
        return False
    if not plausible_person_name(name + ' Placeholder'):
        return False
    lines = [line.strip() for line in str(quote or '').splitlines() if line.strip()]
    return bool(len(lines) == 3 and len(quote) <= 350 and lines[0] == name
                and lines[2].casefold() == email.casefold() and '@' not in lines[1]
                and re.fullmatch(r'[^\s;@]+@[^\s;@]+\.[^\s;@]+', email)
                and re.search(r'\b(manager|director|head|chief|founder|owner|procurement|purchasing|buyer|sourcing|operations|supply chain)\b', lines[1], re.I))
