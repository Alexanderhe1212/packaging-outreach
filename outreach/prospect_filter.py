"""Reject explicit industrial machinery suppliers, not consumer product brands."""
import re

_MACHINE = r'(?:filling|packaging|packing|bottling|labelling|labeling|sealing|injection[ -]moulding|injection[ -]molding)'
_COMPANY = re.compile(r'\b(?:machinery|intelligent machines?|packaging equipment|filling equipment)\b|包装机械|灌装设备|机械制造', re.I)
_PRODUCT = re.compile(r'\b(?:manufactur(?:er|ers|e|es|ing)|suppl(?:ier|iers|y)|speciali[sz](?:e|es|ing) in)\s+(?:of\s+|in\s+)?(?:automated?\s+|industrial\s+)?'+_MACHINE+r'(?:\s*(?:,|and|&)\s*'+_MACHINE+r')*\s+(?:machines?|machinery|equipment)\b', re.I)

def reason(company='', text=''):
    if _COMPANY.search(company or '') or _PRODUCT.search(text or ''):
        return '非目标客户：工业机械或包装设备供应商；保留记录，不进入自动开发'
    return ''

def prospect_reason(prospect):
    evidence=prospect.get('discovery_evidence') or {}
    return reason(prospect.get('company',''), ' '.join(str(prospect.get(k) or '') for k in ('site_description','product_name'))+' '+str(evidence.get('official_page_excerpt') or ''))
