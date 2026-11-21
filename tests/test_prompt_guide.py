"""Check authored guide semantics against the real creation-only planner, without inference."""
import copy
import json
import re
from pathlib import Path
import unittest

from kimodo_generation import plan
from body_contacts import kind, requirements
from textconstraints import contact_owners

ROOT=Path(__file__).resolve().parents[1]
EXAMPLES=json.loads((ROOT/'src/lib/text/prompt-examples.json').read_text(encoding='utf-8'))


def payload(example):
    return dict(output='pose',mode='create',bodyGenerator='kimodo',prompt=example['prompt'],
                actors=[dict(id=i+1,rigId='g8f' if i==0 else 'g9') for i in range(example['actors'])],
                handShapes=example['handShapes'],style='natural',creative=True,candidateCount=3)


class PromptGuideTests(unittest.TestCase):
    def test_all_24_authored_examples_have_the_documented_semantics(self):
        self.assertEqual(len(EXAMPLES),24)
        self.assertEqual(len({e['id'] for e in EXAMPLES}),24)
        for example in EXAMPLES:
            with self.subTest(example=example['id']):
                args=payload(example);original=copy.deepcopy(args)
                value=plan(ROOT,args,{},None,lambda *_:None);expected=example['checks']
                self.assertEqual(value['status'],'plan',value)
                self.assertEqual(args,original)
                self.assertEqual([r['id'] for r in value['actors']],list(range(1,example['actors']+1)))
                self.assertEqual(value['interaction'],expected['interaction'])
                for actor in value['actors']:
                    self.assertEqual(sorted((c['part'],c['movement']) for c in actor['changes']),sorted(map(tuple,expected['changes'])))
                    self.assertEqual(actor['support'],expected.get('actorSupport',{}).get(str(actor['id']),expected['support']))
                    self.assertFalse(actor['expression'])
                    self.assertFalse(actor['preserve'])
                    self.assertEqual(actor['bodyDescription'],example['prompt'])
                    for key,wanted in expected.get('design',{}).items():self.assertEqual(actor.get('design',{}).get(key),wanted)
                self.assertEqual(kind(example['prompt']),expected['floor'])
                for key,wanted in expected.get('requirements',{}).items():self.assertEqual(requirements(example['prompt'])[key],wanted)
                if 'owners' in expected:
                    self.assertEqual([[int(m[1]),m[2][0] if m[2] else None] for m in contact_owners(example['prompt'])],expected['owners'])
                self.assertLessEqual(len(example['prompt']),2000)

    def test_required_gesture_toggle_is_not_silently_optional(self):
        for example in EXAMPLES:
            if example['handShapes']:
                with self.subTest(example=example['id']):
                    value=plan(ROOT,dict(payload(example),handShapes=False),{},None,lambda *_:None)
                    self.assertEqual(value['status'],'clarify')
                    self.assertIn('Approximate hand shapes',value['message'])

    def test_documented_unsupported_or_ambiguous_requests_do_not_become_plans(self):
        cases=[
            ('The left arm is up and the left arm is down.',1,False,'clarify'),
            ('Raise the hand on screen left.',1,False,'clarify'),
            ("Do not raise the left arm.",1,False,'clarify'),
            ('Both people hold hands overhead facing each other.',2,False,'clarify'),
            ('Person 1 uses the right hand and Person 2 uses the left hand for holding hands.',2,False,'clarify'),
            ('A person holds a one-hand handstand.',1,False,'clarify'),
            ('A person crawls with one hand.',1,False,'clarify'),
            ('A smile with cheek puff and tongue out.',1,False,'unsupported'),
            ('Match this reference image.',1,False,'clarify'),
            ('Person 1 carries Person 2.',2,False,'unsupported'),
            ('Her left arm is up.',2,False,'clarify'),
            ('Keep the hips unchanged and raise the left arm.',1,False,'clarify'),
            ('Create an animation.',1,False,'unsupported')
        ]
        for prompt,actors,hands,status in cases:
            with self.subTest(prompt=prompt):
                value=plan(ROOT,payload(dict(prompt=prompt,actors=actors,handShapes=hands)),{},None,lambda *_:None)
                self.assertEqual(value['status'],status,value)

    def test_precise_degrees_are_not_presented_as_checked_rotation_goals(self):
        # Wording can reach Kimodo without producing a checked numeric goal.
        # The guide must send exact-angle work to Pose Studio, not promise it.
        value=plan(ROOT,payload(dict(prompt='A person raises the left arm 30 degrees.',actors=1,handShapes=False)),{},None,lambda *_:None)
        self.assertEqual(value['status'],'plan')
        self.assertFalse(value['actors'][0]['changes'])

    def test_standalone_skill_worked_prompts_are_valid_without_companion_files(self):
        skill=(ROOT/'skills/kimodo-prompt/SKILL.md').read_text(encoding='utf-8')
        prompts=re.findall(r'```text\n(.*?)\n```',skill,re.S)
        self.assertEqual(len(prompts),6)
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                example=dict(prompt=prompt,actors=2 if 'Person 2' in prompt else 1,handShapes='peace sign' in prompt)
                value=plan(ROOT,payload(example),{},None,lambda *_:None)
                self.assertEqual(value['status'],'plan',value)
                if 'left arm is down' in prompt:self.assertIn(('l_arm','lower'),[(c['part'],c['movement']) for c in value['actors'][0]['changes']])
                if 'both feet in the air' in prompt:self.assertEqual(value['actors'][0]['support'],dict(l='air',r='air'))


if __name__=='__main__':unittest.main()
