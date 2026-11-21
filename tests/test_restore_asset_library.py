import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('restore_assets', Path(__file__).resolve().parents[1]/'tools/restore_asset_library.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class RestoreTests(unittest.TestCase):
    def exercise(self, records, existing=None, content=b'authored fixture\n'):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); library=root/'asset-library';library.mkdir()
            (library/'library-manifest.json').write_text(json.dumps({'source_commit':module.SOURCE_COMMIT,'files':records}),encoding='utf-8')
            if existing is not None:(library/'fixture.txt').write_bytes(existing)
            def git(*args): return content if args[0]=='show' else b''
            with patch.object(module,'ROOT',root),patch.object(module,'git',side_effect=git),patch('sys.argv',['restore']):
                module.main()
                return (library/'fixture.txt').read_bytes() if (library/'fixture.txt').exists() else None

    def record(self, path='asset-library/fixture.txt', content=b'authored fixture\n'):
        return {'path':path,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}

    def test_restores_exact_bytes_and_accepts_identical_existing_file(self):
        self.assertEqual(self.exercise([self.record()]),b'authored fixture\n')
        self.assertEqual(self.exercise([self.record()],existing=b'authored fixture\n'),b'authored fixture\n')

    def test_refuses_overwriting_modified_local_asset(self):
        with self.assertRaisesRegex(ValueError,'Preserving modified'):self.exercise([self.record()],existing=b'local work')

    def test_rejects_escape_and_integrity_mismatch(self):
        with self.assertRaisesRegex(ValueError,'Unsafe asset path'):self.exercise([self.record('asset-library/../outside.txt')])
        with self.assertRaisesRegex(ValueError,'integrity check'):self.exercise([self.record()],content=b'wrong bytes')

if __name__=='__main__':unittest.main()
