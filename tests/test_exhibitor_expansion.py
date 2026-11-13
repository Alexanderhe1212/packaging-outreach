import importlib.util,tempfile,pathlib,unittest
p=pathlib.Path(__file__).parents[1]/'userradar/exhibitor_expansion.py'
s=importlib.util.spec_from_file_location('expansion_test',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Expansion(unittest.TestCase):
 def test_one_review_does_not_block_new_discovery(self):
  with tempfile.TemporaryDirectory() as t:
   m.HOME=pathlib.Path(t);st={'rows':[{'website':'https://example.com','review':'pending'}],'calls_today':0};calls=[]
   m.tick(st,{'enabled':True,'daily_search_calls':6},lambda *a:calls.append(a) or {'id':'mock'})
   self.assertEqual(st['active']['id'],'mock');self.assertIn('example.com',calls[0][1]['idea'])
   persisted=__import__('json').loads((m.HOME/'state.json').read_text());self.assertEqual(persisted['calls_today'],1)
 def test_review_capacity_and_budget_block_calls(self):
  for rows,budget,expected in [([{'review':'pending'}]*15,6,'review_capacity_wait'),([],0,'daily_budget_wait')]:
   st={'rows':rows,'calls_today':0};m.tick(st,{'enabled':True,'daily_search_calls':budget},lambda *a:self.fail('unexpected network'));self.assertEqual(st['status'],expected)
 def test_unlimited_depth_and_domain_dedup(self):
  st={'rows':[{'website':'https://example.com'}]};parent={'website':'https://example.com','depth':1000}
  m.collect(st,{'id':'mock','results':[{'candidate':{'website':'https://www.example.com'}},{'candidate':{'website':'https://other.test'}}]},parent)
  self.assertEqual(len(st['rows']),2);self.assertEqual(st['rows'][-1]['depth'],1001);self.assertEqual(st['rows'][-1]['review'],'pending')
