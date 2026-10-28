"""Physical-product searches, not claims of production capability or buying intent.

Each row is a bounded search direction; terms also extend the existing evidence gate.
Official quotations, product/image QC, mailbox checks and suppression still apply.
"""
import re

# Search families consolidate overlapping suggestions rather than duplicating queries.
PRODUCT_GROUPS = '''
perfume|fragrance|solid perfume|discovery set
skincare|serum|face cream|face mask
cosmetics|lipstick|eyeshadow|mascara
body care|hand cream|body oil|foot care
soap|bath salt|bath bomb|shampoo bar
haircare|beard oil|beard balm|comb
makeup brush|gua sha|facial roller|beauty tool
candle|wax melt
reed diffuser|room spray|incense|essential oil
jewellery|jewelry|necklace|earring|bracelet
watch|watch strap|watch accessory
eyewear|sunglasses|spectacle|lens cleaning
wallet|card holder|passport holder|belt|leather goods
scarf|scarves|tie|socks|gloves|cufflink|hair accessory
chocolate|bonbon|truffle
confectionery|candy|caramel|nougat|liquorice
biscuit|cookie|shortbread|macaron|brownie
coffee|coffee capsule|coffee sampler
tea|matcha|herbal infusion
honey|jam|preserves|olive oil|vinegar|hot sauce|spice|sea salt
nuts|dried fruit|popcorn|pretzel|snack
whisky|whiskey|gin|rum|wine|cocktail|bitters|alcohol-free spirit
supplement|vitamin|collagen|nutrition powder
oral care|toothbrush|dental floss|toothpaste tablet
stationery|fountain pen|notebook|journal|stamp
watercolour|paintbrush|calligraphy|embroidery|knitting
greeting card|postcard|art print|bookmark|book set
board game|playing card|puzzle|chess
model kit|building block|collectible toy
headphone|earbud|speaker|charger|phone accessory|wearable
camera strap|lens filter|microphone accessory|microphone|mic boom|camera
ceramic|mug|drinkware|teacup|tumbler
coaster|napkin ring|bottle opener|measuring spoon|grinder
vase|picture frame|ornament|desktop organiser
pillowcase|blanket|towel|tablecloth|napkin|eye mask
pet grooming|paw balm|pet shampoo
pet collar|leash|pet toy|pet treat
seed kit|seed packet|gardening tool|plant label
resistance band|jump rope|massage ball|yoga strap
luggage tag|travel organiser|camping utensil
car fragrance|car cleaning|car care
musical instrument accessory|guitar string|plectrum|harmonica
caliper|measuring tool|engraving tool|screwdriver
 drill bit|screwdriver bit|sandpaper|small hardware
cabinet handle|door handle|hook|door plaque
shower accessory|tap accessory|soap dish|towel rail
light bulb|small lamp|lighting accessory
sensor|smart switch|doorbell|controller
home camera|alarm accessory
magnifier|binocular accessory|optical accessory
teaching model|educational kit|laboratory teaching tool
barber tool|salon kit|hotel amenity
commemorative coin|medallion|coin collection
stamp collection|collectible ticket
sports memorabilia|trading card|signed merchandise
badge|keyring|acrylic stand|licensed merchandise
miniature|dice|miniature paint
magic prop|card trick
card sleeve|deck box|playmat
wooden construction kit|mechanical model
vinyl record|record accessory
mineral specimen|fossil replica
astronomy accessory|birdwatching accessory
wedding favour|bridesmaid kit|groomsman kit
newborn clothing|baby keepsake
baptism gift|rosary|religious keepsake
graduation keepsake|alumni merchandise
anniversary keepsake|commemorative ornament
photo album|memory book|photo book
pet memorial|paw print kit
memorial book|remembrance keepsake
baby bib|baby hat|baby socks|baby shoes
baby brush|baby care
children cutlery|children cup|children plate
flashcard|alphabet card|math manipulative
STEM kit|science teaching kit
children art kit|clay tool|craft kit
sensory toy|cognitive learning card
children activity kit|birthday kit
bicycle light|handlebar tape|cycle repair kit
 golf ball|golf tee|golf glove|ball marker
fishing lure|fishing line|fly fishing
running belt|reflective accessory|race belt
swim goggle|swim cap|earplug
pilates accessory|fitness accessory
climbing brush|chalk bag
camping light|camping accessory
horse grooming|equestrian care
motorcycle care|motorcycle accessory
car polish|microfibre cloth|interior care
boat care|marine accessory
cleaning tablet|cleaning brush|household cleaning
shoe polish|shoe brush|shoe care
clothes brush|sewing kit|laundry accessory
wood wax|leather care|furniture care
aquarium tool|aquarium ornament
sewing accessory|yarn set|needle set
cookie cutter|piping tool|baking tool
cocktail tool|brewing tool|coffee brewing
jewellery storage|card storage|desktop storage
Christmas ornament|Easter decoration|seasonal decoration
fabric swatch|wallpaper sample|leather sample
flooring sample|wood sample|tile sample|stone sample
paint swatch|colour card|finish sample
hearing aid accessory|hearing protection
orthodontic cleaning kit|retainer case
rehabilitation tool|grip trainer|assistive handle
sleep mask|pillow spray|sleep kit
wig|hair extension|hairpiece
press-on nail|nail sticker|false eyelash|manicure tool
tattoo aftercare|body piercing jewellery
dance accessory|dance shoe accessory|stage accessory
medal|trophy|crystal award
kalimba|whistle|small percussion
'''
GROUPS = [tuple(t.strip() for t in line.split('|')) for line in PRODUCT_GROUPS.splitlines() if line.strip()]
SCENARIOS = [
 'physical Christmas Valentine Mother Father Easter seasonal gift sets and advent calendars',
 'physical sample discovery trial refill and replacement accessory products',
 'corporate gifting employee onboarding membership welcome and conference merchandise kits',
 'hotel spa resort museum gallery tourist attraction and cruise own-label retail products',
 'wedding event graduation anniversary newborn and memorial physical keepsake products',
 'subscription boxes and e-commerce gifting with identifiable physical products',
 'restaurant farm estate winery distillery own-label packaged retail products',
 'photography studio album delivery and property automotive key handover welcome kits',
 'fabric flooring furniture hardware and interior material physical sample presentation kits',
 'private-label retailers gift hamper assemblers and contract manufacturers with specific physical products',
 'design and fulfilment businesses with evidenced physical product kit procurement, not services-only agencies',
 'after-sales replacement accessory return-shipping retail-display and distributor physical sample kits',
]
PACKAGING_FOCUSES = ['physical product businesses: '+', '.join(g) for g in GROUPS]+SCENARIOS
# Match actual product terms in the independently verified quote, not bare "brand"/"product".
LOCAL_PRODUCT_TERMS = 'parfum|savon|bougie|bijou|bijoux|montre|café|thé|tasse|jeu de société|album photo|échantillon|schmuck|uhr|kerze|seife|kaffee|tee|brettspiel|kartenspiel|werkzeug|stoffmuster|tapetenmuster|profumo|sapone|candela|gioielli|orologio|caffè|tazza|gioco da tavolo|campione|jabón|vela|joyería|reloj|juego de mesa|muestra|sieraad|kaars|zeep|koffie|thee|bordspel|stofstaal|ljus|tvål|smycke|brädspel'.split('|')
PRODUCT_ALIASES = 'romper|onesie|bodysuit|jumpsuit|pyjama|pajama|sleepwear|babygrow|babywear|baby clothing|dress|shirt|blouse|underwear|lingerie|swaddle|muslin|bib|bonnet|bootie|hair clip|hairpin|headband|scrunchie|beanie|brooch|bangle|pendant|ring|pendulum|keychain|bow tie|necktie|razor|shaving brush|shaving cream|shaving soap|lip balm|lip gloss|body lotion|sunscreen|conditioner|shampoo|nail polish|cuticle oil|massage oil|reed diffuser refill|whipped soap|bath soak|wax tablet|taper candle|pillar candle|cookie dough|crackers|shortbread biscuit|marshmallow|fudge|toffee|gummy|gummies|nut butter|mustard|chutney|granola|protein bar|syrup|cacao|drill|screw|bolt|nut and bolt|hinge|handle set|door knob|drawer pull|tape measure|ruler|craft knife|scissors|tweezers|pliers|punch tool|chisel|file set|paint set|watercolor|canvas kit|ink bottle|ink cartridge|pencil|crayon|eraser|sketchbook|planner|sticker|washi tape|sealing wax|wax seal|calligraphy nib|crochet hook|knitting needle|embroidery thread|sewing thread|fabric sample|material swatch|sample swatch|tile swatch|wood veneer|palette|paint sample|colour sample|color sample|guitar pick|ukulele|tuning fork|metronome|drumstick|reed case|mouthpiece|bass string|strap lock|dog collar|dog lead|cat toy|dog toy|pet bowl|aquarium ornament|pottery|porcelain|stoneware|bowl|plate|saucer|teapot|carafe|decanter|cutlery|flatware|spoon|fork|tea strainer|tea infuser|tea whisk|matcha whisk|corkscrew|cocktail shaker|jigger|measuring cup|piping nozzle|spatula|pastry brush|baking mould|baking mold|gift hamper|gift basket|welcome kit|onboarding kit|collector card|collectible figurine|action figure|model car|model plane|jigsaw|boardgame'.split('|')
PRODUCT_PATTERN = re.compile(r'(?<!\w)(?:'+'|'.join(re.escape(t) for t in ([t for g in GROUPS for t in g]+LOCAL_PRODUCT_TERMS+PRODUCT_ALIASES))+r')(?:s|es)?(?!\w)',re.I)

def expanded_product_match(quote):
 return bool(PRODUCT_PATTERN.search(quote))
