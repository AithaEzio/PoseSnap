import copy
import importlib.abc
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

import body_profiles
import kimodo_generation
import textpose
from storage import atomic_json

ROOT = Path(__file__).resolve().parents[1]


class KimodoOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'temp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for rig in ('g8f', 'g8m', 'g9'):
            atomic_json(self.root/f'data/rigs/{rig}.json', json.loads((ROOT/f'tests/fixtures/target-fit/{rig}.json').read_text(encoding='utf-8')))
        self.payload = dict(mode='create', output='pose', actors=[dict(id=1, rigId='g8f')], prompt='A ballerina spirals with a leg extended behind', handShapes=True)

    def plan(self, **extra):
        return kimodo_generation.plan(self.root, dict(self.payload, **extra), {}, None, lambda *_: None)

    def test_freeform_creation_reaches_native_body_without_reviewed_template(self):
        intent = self.plan()
        self.assertEqual(intent['status'], 'plan')
        self.assertEqual(intent['actors'][0]['recipe'], 'kimodo')
        self.assertEqual(intent['actors'][0]['bodyDescription'], self.payload['prompt'])
        self.assertFalse(intent['actors'][0]['expression'])

    def test_retired_requests_cannot_reactivate_qwen_references_or_faces(self):
        for extra in (dict(useAi=False), dict(reference=None), dict(output='both'), dict(output='expression'), dict(bodyGenerator='reviewed')):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                textpose.task(dict(self.payload, **extra))
        for prompt in ('A smile', 'Left eye closed', 'Tongue out'):
            self.assertNotEqual(self.plan(prompt=prompt)['status'], 'plan')
        self.assertEqual(self.plan(prompt='A happy dancing body')['status'], 'plan')

    def test_profiles_preserve_explicit_mood_and_change_actual_direction(self):
        for style in body_profiles.PROFILES:
            compiled = body_profiles.direction('A person walks', style)
            self.assertTrue(compiled.startswith('A person walks.'))
            if style != 'natural': self.assertIn(body_profiles.PROFILES[style], compiled)
        self.assertEqual(body_profiles.direction('A sad person walks', 'happy'), 'A person: A sad person walks.')

    def test_hand_toggle_does_not_silently_ignore_requested_gestures(self):
        self.assertEqual(self.plan(prompt='Left hand fist', handShapes=False)['status'], 'clarify')
        self.assertEqual(self.plan(prompt='Left hand down', handShapes=False)['status'], 'plan')

    def test_negated_mood_cannot_be_reintroduced_by_a_profile(self):
        for mood in ('happy','sad','tired','dramatic','expressive'):
            prompt='A person walks, but do not look '+mood
            self.assertEqual(body_profiles.direction(prompt,mood),prompt+'.')


    def test_retired_edits_reject_before_loading_and_do_not_change_inputs(self):
        for rig in ('g8f','g8m','g9'):
            pose=textpose.neutral(self.root,rig,'pose-'+'0'*32,1)
            payload=dict(self.payload,mode='modify',actors=[dict(id=1,rigId=rig)],baselines=[dict(pose=pose)])
            original=copy.deepcopy(payload);runtime=Mock();progress=Mock()
            for run in (lambda:textpose.capability(self.root,payload),
                        lambda:kimodo_generation.plan(self.root,payload,{},None,progress),
                        lambda:kimodo_generation.generate(self.root,payload,{},runtime,progress)):
                with self.assertRaisesRegex(ValueError,'creates new body poses'):run()
            runtime.load.assert_not_called();runtime.clips.assert_not_called();progress.assert_not_called()
            self.assertEqual(payload,original)
            self.assertFalse(list((self.root/'temp/text').glob('*.json')))
        for baseline in ([],None,[dict(pose=pose)]):
            with self.assertRaisesRegex(ValueError,'creates new body poses'):
                textpose.task(dict(self.payload,baselines=baseline))

    def test_accepted_legacy_edits_remain_exportable_and_pending_edits_are_rejected(self):
        from textoutput import accepted
        payload=dict(self.payload,prompt='A standing pose',handShapes=False)
        pose=textpose.neutral(self.root,'g8f','pose-'+'0'*32,1)
        pose['bodyGenerator']=dict(provider='synthetic-test-fixture')
        intent=kimodo_generation.plan(self.root,payload,{},None,lambda *_:None)
        record=textpose._generate_one(self.root,payload,intent,lambda *_:None,body_seeds=[pose])
        record['mode']='modify'
        record['signature']=textpose.signature({k:v for k,v in record.items() if k!='signature'})
        path=self.root/'data/text'/f"{record['id']}.json"
        atomic_json(path,record);original=path.read_bytes()
        body,face=accepted(self.root,dict(id=record['id'],actorId=1))
        self.assertEqual(body,record['poses'][0]);self.assertIsNone(face)
        self.assertEqual(path.read_bytes(),original)
        atomic_json(self.root/'temp/text'/f"{record['id']}.json",record)
        with self.assertRaisesRegex(ValueError,'retired generation workflow'):
            textpose.accept(self.root,dict(id=record['id'],signature=record['signature']))

    def test_worker_migration_and_body_planning_with_all_qwen_imports_blocked(self):
        atomic_json(self.root/'data/settings.json', dict(theme='neon', clueEnabled=False, textPack='qwen-local-v1', textDevice='gpu', textVision=True))
        guard = '''import importlib.abc,sys,runpy
class Retired(importlib.abc.MetaPathFinder):
 def find_spec(self,name,path=None,target=None):
  if name in ('qwen','qwen_pack','textprompts','textpack','visual_observer'):raise AssertionError('Retired import: '+name)
sys.meta_path.insert(0,Retired())
sys.path.insert(0,sys.argv[1]);sys.argv=[sys.argv[1]+'/main.py','--root',sys.argv[2]]
runpy.run_path(sys.argv[0],run_name='__main__')
'''
        requests = [('status', {}), ('text_status', {}), ('text_plan', self.payload),
                    ('settings', dict(textHandShapes=False)), ('status', {}),
                    ('settings', dict(textHandShapes=True)), ('status', {})]
        inputs = ''.join(json.dumps(dict(version=1,jobId='migration-'+str(i), method=m, payload=p))+'\n' for i, (m, p) in enumerate(requests))
        run = subprocess.run([str(ROOT/'runtime/python/python.exe'), '-B', '-c', guard, str(ROOT/'worker'), str(self.root)], input=inputs, capture_output=True, text=True, encoding='utf-8', timeout=45)
        self.assertEqual(run.returncode, 0, run.stderr)
        values = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
        errors = [v for v in values if v.get('type')=='error']
        self.assertFalse(errors, errors)
        responses = [v for v in values if 'result' in v]
        self.assertEqual(len(responses), 7, values)
        self.assertFalse(responses[0]['result']['settings']['textHandShapes'])
        self.assertFalse(responses[1]['result']['settings']['textHandShapes'])
        self.assertFalse(responses[3]['result']['textHandShapes'])
        self.assertFalse(responses[4]['result']['settings']['textHandShapes'])
        self.assertTrue(responses[5]['result']['textHandShapes'])
        self.assertTrue(responses[6]['result']['settings']['textHandShapes'])
        saved = json.loads((self.root/'data/settings.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['theme'], 'neon')
        self.assertTrue(saved['textHandShapes'])
        self.assertNotIn('textPack', saved)


if __name__ == '__main__': unittest.main()
