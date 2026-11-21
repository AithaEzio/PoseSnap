from pathlib import Path
import tempfile
import unittest

import qualification
from storage import atomic_json

ROOT=Path(__file__).resolve().parents[1]


class QualificationTests(unittest.TestCase):
    def test_changed_prompt_invalidates_workflow_evidence_without_removing_history(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'temp') as folder:
            root=Path(folder);path=root/'worker/body_profiles.py';path.parent.mkdir();path.write_text('version=1')
            accepted=root/'data/text/accepted.json';atomic_json(accepted,dict(poses=[dict(rotations=dict(hip=[1,2,3]))]))
            original=accepted.read_bytes()
            atomic_json(root/'worker/capability-qualification.json',dict(capabilities={key:dict(status='qualified',componentSignature=qualification.signature(key,root),evidenceRevision='fixture',scope='Test scope') for key in ('pose','floor','interaction')}))
            self.assertTrue(all(r['status']=='qualified' for r in qualification.records(root) if r['id'] in ('pose','floor','interaction')))
            path.write_text('version=2')
            changed=[r for r in qualification.records(root) if r['id'] in ('pose','floor','interaction')]
            self.assertTrue(all(r['status']=='experimental' and not r['compatible'] for r in changed))
            self.assertEqual(accepted.read_bytes(),original)

    def test_missing_optional_head_changes_only_its_compatibility_record(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'temp') as folder:
            root=Path(folder);before={key:qualification.signature(key,root) for key in ('pose','clue-body')}
            head=root/'models/diagnostics/clue/sam3dbody_clue.safetensors';head.parent.mkdir(parents=True);head.write_bytes(b'fixture-only')
            self.assertNotEqual(before['clue-body'],qualification.signature('clue-body',root))
            self.assertEqual(before['pose'],qualification.signature('pose',root))


if __name__=='__main__':unittest.main()
