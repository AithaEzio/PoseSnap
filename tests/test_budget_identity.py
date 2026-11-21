import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'training'))
from pilot_budget import additional_bytes
from common import write


class BudgetIdentityTests(unittest.TestCase):
    def test_windows_versions_and_hardlinks_count_same_file_once(self):
        with patch('pilot_budget.os.name','nt'):
            self.assertEqual(additional_bytes({'16027439442090726231:1125899908139659':204987232},
                {'1827083095:1125899908139659':204987232}),0)
            self.assertEqual(additional_bytes({'16027439442090726231:10':100},
                {'1827083095:10':115,'1827083095:11':20}),35)

    def test_other_volumes_and_file_ids_are_still_new(self):
        with patch('pilot_budget.os.name','nt'):
            self.assertEqual(additional_bytes({'1827083095:10':100},{'1827083096:10':100,'1827083095:11':50}),150)

    def test_conflicting_duplicate_identity_is_rejected(self):
        with patch('pilot_budget.os.name','nt'):
            with self.assertRaisesRegex(ValueError,'Conflicting'):
                additional_bytes({'16027439442090726231:10':100,'1827083095:10':101},{})

    def test_receipt_replace_retries_windows_reader_without_erasing_old_value(self):
        root=Path(__file__).resolve().parents[1]/'temp'
        with tempfile.TemporaryDirectory(dir=root) as folder:
            target=Path(folder)/'receipt.json';target.write_text('old')
            replace=Path.replace;calls=[]
            def transient(source,destination):
                calls.append(1)
                if len(calls)<3:
                    self.assertEqual(target.read_text(),'old')
                    raise PermissionError('Windows reader retains a handle')
                return replace(source,destination)
            with patch('common.os.name','nt'),patch('common.time.sleep'),patch.object(Path,'replace',transient):write(target,dict(complete=True))
            self.assertEqual(len(calls),3);self.assertIn('true',target.read_text())


if __name__=='__main__':unittest.main()
