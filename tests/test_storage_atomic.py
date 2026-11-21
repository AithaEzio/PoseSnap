import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import storage

ROOT=Path(__file__).resolve().parents[1]


class AtomicStorageTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'temp/storage-tests';folder.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=folder);self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'state.json'
        storage.atomic_json(self.path,dict(version=1))

    @unittest.skipUnless(os.name=='nt','Windows file-sharing regression')
    def test_brief_reader_does_not_lose_the_next_complete_state(self):
        reader=self.path.open('rb')
        timer=threading.Timer(.1,reader.close);timer.start()
        try:storage.atomic_json(self.path,dict(version=2))
        finally:timer.join();reader.close()
        self.assertEqual(storage.read_json(self.path),dict(version=2))
        self.assertFalse(self.path.with_suffix('.json.pending').exists())

    def test_persistent_denial_retains_prior_state_and_reports_error(self):
        with patch('storage.os.replace',side_effect=PermissionError('Blocked')),patch('storage.time.sleep'):
            with self.assertRaises(PermissionError):storage.atomic_json(self.path,dict(version=2))
        self.assertEqual(storage.read_json(self.path),dict(version=1))
        self.assertEqual(storage.read_json(self.path.with_suffix('.json.pending')),dict(version=2))


if __name__=='__main__':unittest.main()
