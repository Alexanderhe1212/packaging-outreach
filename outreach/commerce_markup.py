"""Read visible commerce markup; no requests, scripts, inferred products or forms submitted."""
from html.parser import HTMLParser
from urllib.parse import urljoin

class CommercePage(HTMLParser):
    def __init__(self, doc):
        super().__init__(convert_charrefs=True)
        self.title=[]; self.in_h1=False; self.item=False; self.catalog=False
        self.product=False; self.cart=False; self.images=[]; self.image_link=''
        self.card=False; self.links=[]; self.description_parts=[]; self.description_depth=0
        self.feed(doc)
    def handle_starttag(self, tag, pairs):
        a=dict(pairs); classes=a.get('class','').split()
        if tag=='div':
            if self.description_depth: self.description_depth+=1
            elif a.get('id')=='tab-description' or 'woocommerce-product-details__short-description' in classes:
                self.description_depth=1
        if tag=='h1':
            self.in_h1=True
            self.item |= a.get('id')=='item-contenttitle'
            self.catalog |= a.get('id')=='section-contenttitle'
        if any(c.startswith('product-type-') for c in classes): self.product=True
        if tag=='form' and ('cart' in classes or (self.item and a.get('method','').lower()=='post')): self.cart=True
        if tag=='div' and a.get('id')=='section-image-container': self.card=True
        if tag=='a':
            self.image_link=a.get('href','') if 'item-images' in a.get('rel','').split() else ''
            if self.card: self.links.append(a.get('href','')); self.card=False
        if tag=='img': self.images.append((a,self.image_link))
    def handle_endtag(self,tag):
        if tag=='div' and self.description_depth:self.description_depth-=1
        if tag=='h1':self.in_h1=False
        if tag=='a':self.image_link=''
        if tag=='div':self.card=False
    def handle_data(self,data):
        if self.description_depth and data.strip():self.description_parts.append(data.strip())
        if self.in_h1 and data.strip() and data.strip() not in self.title:self.title.append(data.strip())
    @property
    def description(self):
        return ' '.join(self.description_parts)[:2000]
    def product_data(self,url):
        name=' '.join(self.title).strip()
        if not name or not self.cart or not (self.product or self.item):return None
        for a,link in self.images:
            if ' '.join(a.get('alt','').split()).casefold()!= ' '.join(name.split()).casefold():continue
            image=a.get('data-large_image') if self.product else link
            if not image and self.product and {'attachment-full','size-full'} <= set(a.get('class','').split()):
                image=a.get('src')
            if image:
                return dict(name=name,url=url,image_url=urljoin(url,image),price='',facts=[],description=self.description,source='commerce_markup')
        return None
