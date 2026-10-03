"""Product knowledge is configuration; discovery and delivery are shared infrastructure."""
import copy
from . import materials

PACKAGING = {
    'id': 'premium-packaging', 'name': 'Premium custom packaging',
    'offer': 'Custom premium rigid packaging for the customer’s actual product.',
    'target': 'Premium fragrance, jewelry and suitable consumer gift brands in developed markets.',
    'design_rules': 'Two different opening structures, coherent closures and fitted product support. '
        'Premium finishes, brand-informed colors. Ribbon anchors must clear cavities and closing paths. '
        'Do not force handles or filler. Filler is not sole bottle support. Tissue means wrapping tissue.',
    'validation_note': 'Dimensions, fit and closure require sample validation.',
    'price_policy': {'required': True, 'minimum': 100, 'currencies': ['USD', 'EUR']},
    'structures': materials.BOXES, 'supports': materials.INSERTS,
    'accessories': materials.ACCESSORIES,
}


def resolve(config, brand=None):
    key = (brand or {}).get('product_profile', config.get('product_profile', 'premium-packaging'))
    if key == 'premium-packaging':
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
