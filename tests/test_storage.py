import base64,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from packaging_outreach.store import Store
from packaging_outreach import blobs,materials

PNG=base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()

class StorageTests(unittest.TestCase):
    def test_job_and_checkpoint_share_one_verified_file(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);jid=s.add('a',{'concept_png':PNG})
            result=s.cached_call(jid,'image',lambda _: {'png_base64':PNG})
            self.assertEqual(result,{'png_base64':PNG})
            with s.db() as c:
                self.assertNotIn(PNG,c.execute('SELECT payload FROM jobs').fetchone()[0])
                self.assertNotIn(PNG,c.execute('SELECT output FROM runs').fetchone()[0])
            self.assertEqual(len(list((Path(d)/'image-assets').glob('*.png'))),1)
            self.assertEqual(s.get(jid)['payload']['concept_png'],PNG)
            self.assertEqual(s.cached_call(jid,'image',lambda _:self.fail('replayed')),result)
            self.assertEqual(Store(d).get(jid)['payload']['concept_png'],PNG)
    def test_metadata_queries_do_not_open_images(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);s.add('a',{'concept_png':PNG,'plan':{'a':{'box':'drawer'},'b':{'box':'shoulder'}}},'draft')
            with patch.object(blobs,'hydrate',side_effect=AssertionError('image read')):
                self.assertEqual(len(s.queue()),1);self.assertEqual(len(s.status()['jobs']),1)
                self.assertEqual(materials.context(s)['recent_selections'][0],{'a':'drawer','b':'shoulder'})
    def test_corruption_is_visible_but_failure_state_is_recordable(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);jid=s.add('a',{'concept_png':PNG})
            next((Path(d)/'image-assets').glob('*.png')).write_bytes(b'corrupt')
            with self.assertRaises(ValueError):s.get(jid)
            s.fail(jid,'blocked','Image asset changed')
            self.assertEqual(s.get(jid,load_images=False)['state'],'blocked')
    def test_legacy_inline_records_stay_readable(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);jid=s.add('a',{})
            with s.db() as c:c.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps({'concept_png':PNG}),jid))
            self.assertEqual(s.get(jid)['payload']['concept_png'],PNG)
            s.advance(jid,'draft',s.get(jid)['payload'])
            self.assertIsInstance(s.get(jid,load_images=False)['payload']['concept_png'],dict)
