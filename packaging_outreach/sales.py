"""Small grounded email slots; fixed layout, service claims and one reply question."""
import re
from .sources import normalize

REPLY_QUESTION = 'Would you like a short materials and structure breakdown for A or B? Just reply A or B.'
PACKAGING_REPLY_QUESTION = 'Would you like a short materials and insert breakdown for A or B? Just reply A or B.'


CARDSTOCK_MOQ = 'For these cardstock concepts, production starts at 1,000 pieces.'


def brief(payload, profile, brand):
    """Only task-relevant facts and user-configured services go to the writing model."""
    services = brand.get('services', {'concepts': 'These are product-specific concepts for a custom solution.'})
    if not isinstance(services, dict) or not services or any(not isinstance(k,str) or not isinstance(v,str) or not v.strip() or len(v)>400 for k,v in services.items()):
        raise ValueError('services must map IDs to short, factual seller statements')
    result = {
        'company': payload['company'],
        'facts': payload['facts'][:6],
        'product_reference': {'unit_count': payload['product_reference']['unit_count']},
        'seller_profile': {k:profile[k] for k in ('id','name','offer','design_rules','validation_note')},
        'sender_name': brand['name'],
        'services': services,
        'reply_question': PACKAGING_REPLY_QUESTION if profile['id'] in ('paper-packaging','premium-packaging') else REPLY_QUESTION,
    }
    if payload.get('packaging_tier'):
        result['packaging_tier']=payload['packaging_tier']
        result['minimum_order_quantity']=payload.get('minimum_order_quantity')
    return result


def compose(slots, data):
    """No model is needed to assemble layout, approved services and the CTA."""
    limits = {'subject':120,'opening':500,'a_value':450,'b_value':450}
    for field,limit in limits.items():
        value=slots.get(field)
        if not isinstance(value,str) or not value.strip() or len(value)>limit or '\n' in value or '\r' in value:
            raise ValueError('Invalid concise email field: '+field)
        if '?' in value:raise ValueError('The application adds the single reply question')
        if re.search(r'(?i)\bMOQ\b|minimum order',value):raise ValueError('The application adds validated MOQ terms')
    index=slots.get('fact_index')
    if type(index) is not int or not 0<=index<len(data['facts']):raise ValueError('Email needs a verified product fact index')
    fact=data['facts'][index]
    if normalize(fact) not in normalize(slots['opening']):raise ValueError('Opening must include the selected literal product fact')
    service_id=slots.get('service_id')
    if service_id not in data['services']:raise ValueError('Unknown seller service; do not invent capabilities')
    paragraphs=[slots['opening'].strip(),'A — '+slots['a_value'].strip(), 'B — '+slots['b_value'].strip()]
    if data.get('packaging_tier')=='folding_carton':
        if data.get('minimum_order_quantity')!=1000:raise ValueError('Cardstock MOQ must be 1000')
        paragraphs.append(CARDSTOCK_MOQ)
    paragraphs.extend([data['services'][service_id],data['seller_profile']['validation_note'],data.get('reply_question',REPLY_QUESTION)])
    body='\n\n'.join(paragraphs)
    if len(body)>2400:raise ValueError('Email must remain concise')
    return {'subject':slots['subject'].strip(),'body':body,
            'grounding':{'fact_index':index,'fact':fact,'service_id':service_id},
            'reply_goal':'choose_a_or_b'}


def add_packaging_terms(body, payload):
    """Insert the fixed MOQ outside model-generated copy."""
    if payload.get('packaging_tier')!='folding_carton':return body
    if payload.get('minimum_order_quantity')!=1000:raise ValueError('Cardstock MOQ must be 1000')
    if re.search(r'(?i)\bMOQ\b|minimum order',body):raise ValueError('Model-generated MOQ text is not allowed')
    parts=body.split('\n\n')
    at=len(parts)-1 if parts and '?' in parts[-1] else len(parts)
    parts.insert(at,CARDSTOCK_MOQ)
    return '\n\n'.join(parts)
