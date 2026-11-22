"""English scripts use the same native content hash and approval checks."""
import unittest
from engine.longform_contract import full_script,script_hash,validate_approved_script

class EnglishContractTests(unittest.TestCase):
    def contract(self,language='en'):
        first='Keep the script locked. '+('Review the source before making a production decision. '*10)
        second='Check the revision. '+('Each chapter must preserve its approved spoken text. '*10)
        data={'schema_version':'1.0','language':language,'run_id':'english-contract-test','script_locked':True,'title':'A source led production','thumbnail_promise':'Keep the approved script intact','hook':'Keep the script locked.','target_minutes':2,'audience_profile':'English speaking builders','chapters':[{'id':'C01','title':'Lock the script','spoken_text':first},{'id':'C02','title':'Check the revision','spoken_text':second}],'avatar_appearances':2}
        data['target_minutes']=len(full_script(data).split())/145
        data['script_hash']=script_hash(full_script(data));return data
    def test_english_accepts_ascii_without_weakening_hash(self):
        data=self.contract();self.assertEqual(validate_approved_script(data),[])
        data['chapters'][0]['spoken_text']+=' A changed sentence.'
        self.assertTrue(any('script_hash' in e for e in validate_approved_script(data)))
    def test_spanish_and_default_keep_diacritic_guard(self):
        data=self.contract('es');self.assertTrue(any('diacriticos' in e for e in validate_approved_script(data)))
        del data['language'];self.assertTrue(any('diacriticos' in e for e in validate_approved_script(data)))
    def test_unknown_language_rejected(self):
        self.assertIn('language must be es or en',validate_approved_script(self.contract('xx')))

if __name__=='__main__':unittest.main()
