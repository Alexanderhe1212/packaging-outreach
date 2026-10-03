"""Add a public company-team greeting without inventing a contact name."""
import re


def with_greeting(body, company):
    name=' '.join(company.split()).strip()
    if not name:
        raise ValueError('Public company name required for greeting')
    body=body.lstrip()
    first=body.split('\n',1)[0].strip()
    if re.fullmatch(r'(?:Hi|Hello|Dear)\s+[^\n]{1,160}[,!]?',first,re.I):
        return body
    return 'Hi '+name+' Team,\n\n'+body
