import copy,time,unittest
from unittest.mock import patch
from outreach import distributor as d
class Review(unittest.TestCase):
 def test_approval_bound_to_every_send_field(self):
  l=dict(id=1,account='GUKA',domain='example.com',email='sales@example.com',subject='Paper bags',body='Hi Example team,',data={})
  l['data']['distributor_review']=dict(kind='packaging_distributor',digest=d.digest(l),public_email_verified=True,approved=True,product_quote='Branded paper bags and product boxes',source_url='https://example.com/products',exhibitor_url='https://event.test/exhibitor',exhibitor_quote='Example Packaging distributor',checked_at=time.time())
  self.assertTrue(d.eligible(l))
  for k in ('id','account','domain','email','subject','body'):
   other=copy.deepcopy(l);other[k]='changed';self.assertFalse(d.eligible(other),k)
  l['data']['distributor_review']['checked_at']=0;self.assertFalse(d.eligible(l))
 def test_excerpts_require_actual_source(self):
  with patch.object(d.web,'page',return_value=('<p>Other products entirely</p>','https://example.com/products')):
   with self.assertRaises(ValueError):d.excerpt('https://example.com/products','Branded paper bags and product boxes','example.com')
 def test_sent_record_cannot_prepare(self):
  with patch.object(d.store,'lead',return_value=dict(id=1,status='sent')):
   with self.assertRaises(ValueError):d.prepare({'id':1})
