"""Rule-based evidence triage, not a claim of purchase intent."""
import re
from bs4 import BeautifulSoup

PATTERNS = {
    '明确包装场景': r'\b(packaging|gift boxes?|cartons?|bottles?|pouches?|containers?|labels?|tins?)\b|包装|礼盒|纸箱|标签',
    '品牌与代工场景': r'\b(private label|own brand|contract manufacturing|co-packing|white label)\b|自有品牌|代工|贴牌',
    '供应商采购入口': r'\b(supplier registration|become a supplier|vendor registration|supplier portal)\b|供应商注册|供应商招募',
}

def evidence(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script','style','nav','footer','header']): tag.decompose()
    found=[]
    for tag in soup.find_all(['p','li','h1','h2','h3']):
        text=tag.get_text(' ',strip=True)
        if not 12 <= len(text) <= 650: continue
        for category, pattern in PATTERNS.items():
            if re.search(pattern,text,re.I):
                item={'category':category,'text':text,'source':url}
                if item not in found: found.append(item)
    return found[:15]

def assess(result):
    items=result.get('business_evidence',[])
    categories={item['category'] for item in items}
    related=bool(categories)
    result['business_fit']={
        'label':'有包装相关证据，建议人工评估' if related else '包装业务相关性证据不足',
        'method':'官网原文关键词初筛，非 AI 采购预测',
        'evidence':items,
        'missing':['尚未确认采购预算、采购时间和采购数量','尚未确认联系人是否负责包装采购'],
        'priority':'优先核实' if related and result.get('qualified_people') else '继续补查',
    }
    return result
