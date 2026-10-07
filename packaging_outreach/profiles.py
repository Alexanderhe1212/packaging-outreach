"""Product knowledge is configuration; discovery and delivery are shared infrastructure."""
import copy
from . import materials

PACKAGING = {
    'id': 'premium-packaging', 'name': 'Premium custom packaging',
    'offer': 'Custom premium product-fitting paper packaging for the customer’s actual product.',
    'target': 'Premium fragrance, jewelry and suitable consumer gift brands in developed markets.',
    'design_rules': 'Two different opening structures, coherent closures and fitted product support. '
        'Premium finishes, brand-informed colors. Ribbon anchors must clear cavities and closing paths. '
        'Do not force handles or filler. Filler is not sole bottle support. Tissue means wrapping tissue.',
    'validation_note': 'Dimensions, fit and closure require sample validation.',
    'price_policy': {'required': True, 'minimum': 0, 'currencies': ['USD']},
    'price_tier_policy': {
        'version': 'usd50-v1', 'threshold_usd': 50,
        'folding_carton_moq': 1000,
        'folding_carton_structures': list(materials.FOLDING_CARTONS),
        'rigid_box_structures': list(materials.RIGID_BOXES),
        'folding_carton_supports': materials.FOLDING_CARTON_SUPPORTS,
    },
    'structures': materials.BOXES, 'supports': materials.INSERTS,
    'accessories': materials.ACCESSORIES,
}


PAPER_PACKAGING = copy.deepcopy(PACKAGING)
PAPER_PACKAGING.update(id='paper-packaging', name='Custom paper and gift packaging',
    offer='Custom paper boxes, gift boxes and product-fitting paper packaging.',
    target='Food, beverage, beauty, personal care, electronics, apparel, accessories, DTC, '
        'gifts, stationery, wellness outer packaging, design agencies, print resellers and publicly operating artisans. '
        'Use published business contacts and actual products. No minimum retail price or business size. '
        'Do not infer purchase intent, MOQ, food-contact or medical certification.',
    price_policy={'required':True,'minimum':0,'currencies':['USD']})


def resolve(config, brand=None):
    key = (brand or {}).get('product_profile', config.get('product_profile', 'premium-packaging'))
    if key == 'paper-packaging':
        result = copy.deepcopy(PAPER_PACKAGING)
    elif key == 'premium-packaging':
        result = copy.deepcopy(PACKAGING)
    else:
        result = copy.deepcopy(config.get('product_profiles', {}).get(key, {}))
        if not result:
            raise ValueError('Unknown product profile: ' + key)
        result['id'] = key
    for field in ('name', 'offer', 'target', 'design_rules', 'validation_note'):
        if not isinstance(result.get(field), str) or not result[field].strip():
            raise ValueError('Product profile requires ' + field)
    if not isinstance(result.get('structures'), dict) or len(result['structures']) < 2:
        raise ValueError('Product profile requires at least two structures')
    if not isinstance(result.get('supports'), list) or not result['supports']:
        raise ValueError('Product profile requires support choices (use none where appropriate)')
    if not isinstance(result.get('accessories', []), list):
        raise ValueError('Product profile accessories must be a list')
    result.setdefault('accessories', [])
    result.setdefault('price_policy', {'required': False})
    policy = result['price_policy']
    if not isinstance(policy, dict):
        raise ValueError('price_policy must be an object')
    minimum = policy.get('minimum', 0)
    if type(minimum) not in (int, float) or not 0 <= minimum < float('inf'):
        raise ValueError('Price minimum must be a finite nonnegative number')
    if policy.get('required') and not policy.get('currencies'):
        raise ValueError('Required price needs accepted currencies')
    tier = result.get('price_tier_policy')
    if tier:
        if (tier.get('version') != 'usd50-v1' or tier.get('threshold_usd') != 50 or
                tier.get('folding_carton_moq') != 1000):
            raise ValueError('Built-in packaging price tier must be USD 50 / MOQ 1000')
        folding=set(tier.get('folding_carton_structures',[]));rigid=set(tier.get('rigid_box_structures',[]))
        if (not folding or not rigid or folding & rigid or
                not (folding|rigid) <= set(result['structures']) or
                not set(tier.get('folding_carton_supports',[])) <= set(result['supports'])):
            raise ValueError('Packaging tier catalogue is incomplete')
        if policy.get('required') is not True or policy.get('minimum') != 0 or policy.get('currencies') != ['USD']:
            raise ValueError('Packaging tier requires an exact official USD price without a minimum')
    return result


def apply_price_tier(payload, profile):
    """Bind the verified exact-SKU USD price to a deterministic box tier."""
    rule=profile.get('price_tier_policy')
    if not rule:return payload
    price=payload.get('retail_price',{})
    amount=price.get('amount') if isinstance(price,dict) else None
    if type(amount) not in (int,float) or isinstance(amount,bool) or not 0<=amount<float('inf') or price.get('currency')!='USD':
        raise ValueError('Packaging tier requires an exact official USD product price')
    low=amount<rule['threshold_usd']
    payload['packaging_tier']='folding_carton' if low else 'rigid_box'
    payload['price_rule_version']=rule['version']
    payload['price_tier_rule']={
        'threshold_usd':rule['threshold_usd'],
        'folding_carton_moq':rule['folding_carton_moq'],
    }
    if low:payload['minimum_order_quantity']=rule['folding_carton_moq']
    else:payload.pop('minimum_order_quantity',None)
    return payload


def for_payload(profile, payload):
    """Expose only structures/supports allowed for this verified price tier."""
    output=copy.deepcopy(profile);rule=output.get('price_tier_policy')
    if not rule:return output
    tier=payload.get('packaging_tier')
    if tier=='folding_carton':
        allowed=set(rule['folding_carton_structures'])
        output['supports']=[x for x in output['supports'] if x in rule['folding_carton_supports']]
        output['design_rules']+=' Both A and B must be thin folding cardstock cartons, never rigid greyboard or magnetic boxes.'
        output['minimum_order_quantity']=rule['folding_carton_moq']
    elif tier=='rigid_box':
        allowed=set(rule['rigid_box_structures'])
        output['design_rules']+=' Both A and B must be rigid presentation boxes, not lightweight folding cartons.'
    else:raise ValueError('Verified packaging tier missing')
    output['structures']={k:v for k,v in output['structures'].items() if k in allowed}
    output['packaging_tier']=tier;output['price_rule_version']=rule['version']
    return output


def public(profile):
    fields=('id','name','offer','design_rules','validation_note','packaging_tier','minimum_order_quantity','price_rule_version')
    return {k:profile[k] for k in fields if k in profile}


def validate_price_tier_payload(payload):
    """Final hard gate: stale or mismatched price-tier drafts cannot be sent."""
    profile=payload.get('seller_profile',{});rule=profile.get('price_tier_policy')
    if not rule:
        if profile.get('id') in ('paper-packaging','premium-packaging'):
            raise ValueError('Packaging draft predates the required USD 50 tier rule')
        return
    price=payload.get('retail_price',{});amount=price.get('amount') if isinstance(price,dict) else None
    if (type(amount) not in (int,float) or isinstance(amount,bool) or price.get('currency')!='USD' or
            not price.get('checked_at') or price.get('product_url')!=payload.get('product_evidence_url') or
            not price.get('source_quote')):
        raise ValueError('Send blocked: exact official USD price evidence is missing')
    expected='folding_carton' if amount<rule['threshold_usd'] else 'rigid_box'
    if payload.get('packaging_tier')!=expected or payload.get('price_rule_version')!=rule['version']:
        raise ValueError('Send blocked: product price and packaging tier do not match')
    plans=payload.get('plan',{});structures=[plans.get(k,{}).get('structure') for k in ('a','b')]
    allowed=rule['folding_carton_structures'] if expected=='folding_carton' else rule['rigid_box_structures']
    if len(set(structures))!=2 or any(x not in allowed for x in structures):
        raise ValueError('Send blocked: A/B structures do not match the price tier')
    if expected=='folding_carton':
        if payload.get('minimum_order_quantity')!=rule['folding_carton_moq']:
            raise ValueError('Send blocked: cardstock MOQ must be 1000')
        if 'production starts at 1,000 pieces' not in payload.get('draft',{}).get('body',''):
            raise ValueError('Send blocked: cardstock MOQ is missing from the email')


def normalize_plan(plan, profile):
    """Accept v0.1 box/insert providers while exposing industry-neutral names."""
    output = {}
    for key in ('a', 'b'):
        option = dict(plan[key])
        option['structure'] = option.pop('box', option.get('structure'))
        option['support'] = option.pop('insert', option.get('support'))
        accessories = option.get('accessories', [])
        if (option['structure'] not in profile['structures'] or
                option['support'] not in profile['supports'] or
                not isinstance(accessories, list) or len(accessories) > 2 or
                any(x not in profile['accessories'] for x in accessories)):
            raise ValueError('Unknown product-profile material selection')
        if not option.get('description') or not option.get('fit_reason'):
            raise ValueError('Each option needs a description and product-specific fit reason')
        option['accessories'] = accessories
        output[key] = option
    if output['a']['structure'] == output['b']['structure']:
        raise ValueError('A and B require distinct structures')
    return output
