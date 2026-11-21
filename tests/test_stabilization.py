import copy
import tempfile
import unittest
from pathlib import Path

from instructions import clauses, negated
from kimodo_generation import explicit_body
from textconstraints import limbs, posture_recipe, preflight,enforce
from hand_design import phrases
from body_contacts import kind, requirements
from soma import airborne_request
from extraction import pure_signature
from wholebody import signature
from unittest.mock import patch
import numpy as np


class StabilizationTests(unittest.TestCase):
    def test_contracted_exclusions_never_become_positive_goals(self):
        for exclusion in ("Don't", 'Don’t', 'Do not', 'Never'):
            with self.subTest(exclusion=exclusion):
                self.assertEqual(explicit_body(exclusion+' turn the head left'), ([], None))
                self.assertEqual(limbs(exclusion+' raise the left arm'), [])
                self.assertEqual(phrases(exclusion+' clench the left hand'), [])
                self.assertFalse(airborne_request(exclusion+' jump'))
                self.assertEqual(kind(exclusion+' kneel'), 'upright')
                payload=dict(mode='create', output='pose', prompt=exclusion+' turn the head left', actors=[dict(id=1,rigId='g9')])
                self.assertEqual(preflight(payload)['status'], 'clarify')
        self.assertEqual(explicit_body('Turn the head left')[0][0]['movement'], 'turn_left')

    def test_conjoined_exclusions_are_conservative_but_contrast_resets_scope(self):
        self.assertEqual(limbs("Don't raise the left arm and bend the right knee"), [])
        self.assertEqual(phrases("Don't clench the left hand and curl the right index finger"), [])
        self.assertEqual(limbs("Don't raise the left arm; lower the right arm"), [dict(part='r_arm',movement='lower',amount=1.)])
        self.assertEqual(posture_recipe("Don't kneel; stand naturally"), 'standing')
        self.assertFalse(requirements("Don't rest both feet flat on the floor")['flatFeet'])

    def test_source_cache_uses_installed_config_code_and_vendor_patch(self):
        root=Path(__file__).resolve().parents[1]/'temp';root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            workspace=Path(folder)
            before=[pure_signature(workspace),signature(workspace)]
            for relative in ('models/body/model_config.yaml', 'vendor/sam-3d-body/sam_3d_body/models/meta_arch/sam3d_body.py','worker/inference.py','worker/sam3dbody_clue/head.py','models/diagnostics/clue/sam3dbody_clue.safetensors'):
                path=workspace/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('version: initial')
                after=[pure_signature(workspace),signature(workspace)]
                self.assertNotEqual(before[0],after[0]);self.assertNotEqual(before[1],after[1])
                before=after
            unused=workspace/'models/body/config.yaml';unused.write_text('unused')
            self.assertEqual(before,[pure_signature(workspace),signature(workspace)])
            accepted=dict(rotations={'hip':[1,2,3]}, expression={'jawOpen':.2});snapshot=copy.deepcopy(accepted)
            pure_signature(workspace)
            self.assertEqual(accepted,snapshot)

    def test_flat_support_cannot_be_satisfied_by_one_touching_toe(self):
        from pose_design import verify_support
        pose=dict(footSupport=[dict(side=s,state='flat') for s in ('l','r')])
        points={s+'_'+p:np.array([0.,8. if p=='heel' else 0.,0.]) for s in ('l','r') for p in ('heel','bigtoe','smalltoe')}
        with patch('measurements.target_points',return_value=(points,{})):
            with self.assertRaises(ValueError):verify_support(pose)
            pose['footSupport']=[dict(side=s,state='toe') for s in ('l','r')]
            verify_support(pose)

    def test_kneeling_gate_keeps_explicit_flat_foot_requirement(self):
        import body_contacts
        pose=dict(bodyContacts=dict(kind='kneel',requirements=dict(kneeSide='r',flatFeet=True)))
        markers={s+'_'+p:8. if p=='heel' else 0. for s in ('l','r') for p in ('heel','bigtoe','smalltoe','knee','palm')}
        joints={'hip':np.array([0.,20.,0.]),'chest':np.array([0.,50.,0.])}
        with patch('body_contacts.surfaces',return_value=(markers,joints,dict(hip='hip',spine4='chest'),1.,{})):
            with self.assertRaises(ValueError):body_contacts.verify(pose)
            pose['bodyContacts']['requirements']=dict(kneeSide='r',feet=dict(l='flat'))
            with self.assertRaises(ValueError):body_contacts.verify(pose)
        self.assertEqual(requirements('Kneeling on the right knee with the left foot flat')['feet'],dict(l='flat'))

    def test_missing_reference_and_conflicting_final_states_clarify_before_inference(self):
        payload=dict(mode='create',output='pose',actors=[dict(id=1,rigId='g9')])
        for text in ('Like the reference, lower the left hand','Left hand up and left hand down'):
            self.assertEqual(preflight(dict(payload,prompt=text))['status'],'clarify')
        self.assertEqual(preflight(dict(payload,prompt='Like the reference, lower the left hand',reference=dict(mode='match',imageId='a'*24)))['status'],'clarify')





    def test_inflected_seated_and_lying_requests_keep_floor_checks_enabled(self):
        for text in ('She sits down with both feet flat.','She sits on the floor.','Sit with both feet flat.','A seated pose.'):
            self.assertEqual(kind(text),'seated');self.assertEqual(posture_recipe(text),'seated')
        for text in ('She lies on her back.','Lie down face up.','A supine pose.'):
            self.assertEqual(kind(text),'lying');self.assertEqual(posture_recipe(text),'lying')
        self.assertEqual(kind("Don't sit down; stand naturally"),'upright')

    def test_flat_soles_share_a_feasible_plane_on_all_three_captured_rigs(self):
        import json,textpose
        from pose_design import fit_support,verify_support
        from measurements import target_points
        from storage import atomic_json
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root/'temp') as folder:
            workspace=Path(folder)
            for rig in ('g8f','g8m','g9'):
                atomic_json(workspace/f'data/rigs/{rig}.json',json.loads((root/f'tests/fixtures/target-fit/{rig}.json').read_text()))
                pose=textpose.neutral(workspace,rig,'pose-'+'0'*32,1);original=copy.deepcopy(pose['rig'])
                # A deliberately uneven synthetic stance exercises the sole fit.
                for side in ('l','r'):
                    sign=1 if side=='l' else -1
                    textpose.aim(pose,side+'_thigh',[sign*.16,-1,.16 if side=='l' else .01])
                    textpose.aim(pose,side+'_shin',[sign*.02,-1,-.14 if side=='l' else .02])
                    textpose.aim(pose,side+'_foot',[sign*.08,0,1])
                support={'l':'flat','r':'flat'}
                fit_support(pose,support);points,_=target_points(pose)
                soles=[points[s+'_'+k][1] for s in ('l','r') for k in ('heel','bigtoe','smalltoe')]
                self.assertLessEqual(max(soles)-min(soles),1.)
                pose['translation'][1]-=float(min(soles));pose['footSupport']=[dict(side=s,state=v) for s,v in support.items()]
                verify_support(pose);self.assertEqual(pose['rig'],original)


if __name__=='__main__':unittest.main()
