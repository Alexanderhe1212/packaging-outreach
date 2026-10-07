"""Product knowledge is configuration; discovery and delivery are shared infrastructure."""
import copy
from . import materials

PACKAGING = {
    'id': 'premium-packaging', 'name': 'Premium custom packaging',
    'offer': 'Custom premium product-fitting paper packaging for the customer’s actual product.',
    'target': 'Premium fragrance, jewelry and suitable consumer gift brands in developed markets.',
    'design_rules': 'Two different opening structures, coherent closures and fitted product support. '
        'Premium finishes, brand-informed colors. Ribbon anchors must clear cavities and closing paths. '
        'Do not force handles or filler. Filler is not sole bottle support. Tissue means wrapping tissue. Choose rigid or carton construction independently for each option from product form, fragility, count, retrieval, packed pose and brand positioning; never from retail price. Folding cartons use folded-card or corrugated support only. Fold soft textiles compactly while preserving pattern, material, fringe and count. Avoid oversized empty boxes and tissue bolsters. Use restrained brand colors, tactile paper and at most two appropriate finishes. Product fit takes priority over novelty.',
    'validation_note': 'Dimensions, fit and closure require sample validation.',
    'price_policy': {'required': False},
    'product_fit_policy': {
        'version': 'product-fit-v1',
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
    price_policy={'required':False})


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
    return result


def apply_product_fit(payload, profile):
    """The catalogue stays available without a required price or currency."""
    if profile.get('product_fit_policy'):
        payload['packaging_rule_version']='product-fit-v1'
    return payload

# Backward-compatible callable; the USD50 policy has been retired.
apply_price_tier = apply_product_fit


def for_payload(profile, payload):
    output=copy.deepcopy(profile)
    if output.get('id') in ('paper-packaging','premium-packaging'):
        # Resume persisted built-in profiles using the current catalogue, not old tier filters.
        current=copy.deepcopy(PAPER_PACKAGING if output['id']=='paper-packaging' else PACKAGING)
        if output.get('material_manifest'):current['material_manifest']=output['material_manifest']
        output=current
    return output


def bind_plan(payload, plan, profile):
    if not profile.get('product_fit_policy'):return {}
    types={k:'folding_carton' if plan[k]['structure'] in materials.FOLDING_CARTONS else 'rigid_box' for k in ('a','b')}
    fields={'packaging_rule_version':'product-fit-v1','option_packaging_types':types,
        'packaging_tier':types['a'] if types['a']==types['b'] else 'mixed'}
    cartons=[k for k in ('a','b') if types[k]=='folding_carton']
    if cartons:fields.update(minimum_order_quantity=1000,cardstock_options=cartons)
    else:payload.pop('minimum_order_quantity',None);payload.pop('cardstock_options',None)
    payload.update(fields)
    return fields


def public(profile):
    fields=('id','name','offer','design_rules','validation_note','product_fit_policy')
    return {k:profile[k] for k in fields if k in profile}


def validate_product_fit_payload(payload):
    profile=payload.get('seller_profile',{})
    if profile.get('id') not in ('paper-packaging','premium-packaging') and not profile.get('product_fit_policy'):return
    current=for_payload(profile,payload)
    plan=normalize_plan(payload.get('plan',{}),current)
    derived=bind_plan({},plan,current)
    if payload.get('packaging_tier')!=derived['packaging_tier']:
        raise ValueError('Construction does not match the selected A/B structures')
    if payload.get('packaging_rule_version')=='product-fit-v1' and payload.get('option_packaging_types')!=derived['option_packaging_types']:
        raise ValueError('Per-option construction differs from the plan')
    if derived.get('cardstock_options'):
        if payload.get('minimum_order_quantity')!=1000:raise ValueError('Cardstock MOQ must be 1000')
        if 'production starts at 1,000 pieces' not in payload.get('draft',{}).get('body',''):
            raise ValueError('Cardstock MOQ is missing from the email')

validate_price_tier_payload = validate_product_fit_payload


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
        if profile.get('product_fit_policy') and option['structure'] in materials.FOLDING_CARTONS and option['support'] not in materials.FOLDING_CARTON_SUPPORTS:
            raise ValueError('Folding cartons require paper support')
        if not option.get('description') or not option.get('fit_reason'):
            raise ValueError('Each option needs a description and product-specific fit reason')
        option['accessories'] = accessories
        output[key] = option
    if output['a']['structure'] == output['b']['structure']:
        raise ValueError('A and B require distinct structures')
    return output
