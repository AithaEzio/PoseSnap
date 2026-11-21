import copy, unittest, tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.spatial.transform import Rotation
from studio import convert_pose, semantics, rest_frame
from retarget import fk
from editor import operation, new_pose, checked_poses, pose_history
from daz import duf
from rigs import pose_bone
from test_interaction import fixture

def target_rig():
    _,pose=fixture(1,0);rig=copy.deepcopy(pose['rig']);rig.update(id='g9',label='Synthetic G9')
    names={'chestUpper':'spine4'}
    for side in ('l','r'):
        for old,new in [('ShldrBend','upperarm'),('ForearmBend','forearm'),('Hand','hand'),('ThighBend','thigh'),('Shin','shin'),('Foot','foot')]:names[side+old]=side+'_'+new
    for n in rig['nodes']:
        n['id']=names.get(n['id'],n['id']);n['parent']=names.get(n['parent'],n['parent']);n['order']='YZX';n['orientation']=[12,-7,20]
    return rig

class StudioTests(unittest.TestCase):
    def test_conversion_and_neutral_mannequins_do_not_add_passive_or_facial_channels(self):
        _,pose=fixture(1,0);target=target_rig()
        for name in ('l_pectoral','r_pectoral','l_eye','lowerjaw','l_lipcorner','l_cheek','tongue01'):
            node=copy.deepcopy(target['nodes'][1]);node.update(id=name,parent='head');target['nodes'].append(node)
        converted=convert_pose(pose,target)
        self.assertEqual(set(converted['rotations']),{n['id'] for n in target['nodes'] if pose_bone(n)})
        self.assertIn('l_forearm',converted['rotations']);self.assertIn('l_hand',converted['rotations'])
        with tempfile.TemporaryDirectory() as folder,patch('editor.profile',return_value=target):
            neutral=new_pose(Path(folder),'g9')
            added=operation(Path(folder),dict(editorOperation='add_mannequin',poses=[neutral],rigId='g9'),lambda *_:None)
        self.assertEqual(set(neutral['rotations']),set(converted['rotations']))
        self.assertEqual(set(added['poses'][1]['rotations']),set(converted['rotations']))

    def test_actual_genesis_profiles_have_the_same_pose_scope_after_conversion(self):
        import json
        root=Path(__file__).resolve().parents[1]
        rigs={id:json.loads((root/'tests/fixtures/target-fit'/f'{id}.json').read_text()) for id in ('g8f','g8m','g9')}
        for source_id,source in rigs.items():
            pose=dict(version=1,rigId=source_id,rig=source,rotations={n['id']:[0,0,0] for n in source['nodes'] if pose_bone(n)},translation=[7,4,-6],rootRotation=[0,10,0],warnings=[])
            for target_id,target in rigs.items():
                if source_id==target_id:continue
                with self.subTest(source=source_id,target=target_id):
                    result=convert_pose(pose,target)
                    self.assertEqual(set(result['rotations']),{n['id'] for n in target['nodes'] if pose_bone(n)})
                    self.assertEqual(result['translation'],[7,4,-6])
                    self.assertFalse(any('pectoral' in name.lower() for name in result['rotations']))

    def test_sequential_bend_twist_and_finger_curl_transfer_both_directions(self):
        def rig(id):
            nodes=[]
            def add(name,parent,center,end,limits=None):nodes.append(dict(id=name,parent=parent,center=center,end=end,type='figure' if not parent else 'bone',orientation=[0,0,0],order='XZY',limits=limits or {}))
            lock=dict(min=0,max=0,clamped=True,locked=True);bend={'x':lock,'y':dict(min=-135,max=20,clamped=True),'z':lock};twist={'x':dict(min=-90,max=80,clamped=True),'y':lock,'z':lock}
            add('figure',None,[0,0,0],[0,10,0]);add('hip','figure',[0,10,0],[0,20,0]);add('head','hip',[0,30,0],[0,40,0])
            if id=='g9':
                add('l_upperarm','hip',[10,20,0],[40,20,0]);add('l_forearm','l_upperarm',[40,20,0],[70,20,0]);add('l_hand','l_forearm',[70,20,0],[80,20,0]);hand='l_hand'
            else:
                add('lShldrBend','hip',[10,20,0],[25,20,0],{'x':lock});add('lShldrTwist','lShldrBend',[25,20,0],[40,20,0],twist)
                add('lForearmBend','lShldrTwist',[40,20,0],[55,20,0],bend);add('lForearmTwist','lForearmBend',[55,20,0],[70,20,0],twist);add('lHand','lForearmTwist',[70,20,0],[80,20,0]);hand='lHand'
            for finger,z in [('Index',2),('Mid',0),('Pinky',-2)]:
                name=lambda segment:'l_'+finger.lower()+str(segment) if id=='g9' else 'l'+finger+str(segment)
                for s in (1,2,3):add(name(s),hand if s==1 else name(s-1),[80+s*3,20,z],[83+s*3,20,z],{'x':lock,'y':lock,'z':dict(min=-105,max=12,clamped=True)})
            return dict(id=id,label=id,sourceId='figure',nodes=nodes)
        rigs={id:rig(id) for id in ('g8f','g9')}
        for source_id,target_id in [('g8f','g9'),('g9','g8f')]:
            source=rigs[source_id];target=rigs[target_id]
            values={'lForearmBend':[0,-35,0],'lForearmTwist':[20,0,0],'l_forearm':[20,-35,0],'lIndex2':[0,0,-40],'l_index2':[0,0,-40]}
            pose=dict(version=1,rigId=source_id,rig=source,rotations={n['id']:values.get(n['id'],[0,0,0]) for n in source['nodes'] if n['parent']},translation=[10,5,-20],rootRotation=[10,15,20],warnings=[])
            next=convert_pose(pose,target);sm=semantics(source);tm=semantics(target);a=fk(source,{**pose['rotations'],'figure':pose['rootRotation']})[0];b=fk(target,{**next['rotations'],'figure':next['rootRotation']})[0]
            for key in ('l_forearm','l_hand','l_index2','l_index3'):
                self.assertLess(np.degrees(Rotation.from_matrix(a[sm[key]].T@b[tm[key]]).magnitude()),.1,source_id+' → '+target_id+' '+key)
    def test_transfer_keeps_edited_body_and_root_world_frames(self):
        _,pose=fixture(1,0);pose.update(rootRotation=[10,25,-8],translation=[40,3,-20],edited=True)
        pose['rotations']['chestUpper']=[6,-12,8];pose['rotations']['lForearmBend']=[24,10,-8]
        original=copy.deepcopy(pose);target=target_rig();target_before=copy.deepcopy(target)
        converted=convert_pose(pose,target);sm=semantics(pose['rig']);tm=semantics(target)
        old=fk(pose['rig'],{**pose['rotations'],'figure':pose['rootRotation']})[0]
        new=fk(target,{**converted['rotations'],'figure':converted['rootRotation']})[0]
        for key in sm.keys()&tm.keys():
            a=old[sm[key]]@rest_frame(pose['rig'],key,sm);b=new[tm[key]]@rest_frame(target,key,tm)
            self.assertLess(np.degrees(Rotation.from_matrix(a.T@b).magnitude()),.1,key)
        self.assertEqual(converted['translation'],pose['translation']);self.assertEqual(pose,original);self.assertEqual(target,target_before)
        self.assertNotEqual(converted['rotations']['l_forearm'],[0,0,0]);self.assertTrue(duf(converted,'floor')['scene']['animations'])
    def test_same_generation_is_exact_and_returns_independent_channels(self):
        _,pose=fixture(1,0);pose['rotations']['lHand']=[11,22,33]
        converted=convert_pose(pose,pose['rig']);self.assertEqual(converted,pose)
        converted['rotations']['lHand'][0]=0;self.assertEqual(pose['rotations']['lHand'][0],11)
    def test_limits_and_driven_axes_are_respected_and_reported(self):
        _,pose=fixture(1,0);pose['rotations']['lForearmBend']=[80,30,20];target=target_rig()
        node=next(n for n in target['nodes'] if n['id']=='l_forearm')
        node['limits']={'x':dict(min=-5,max=5,clamped=True),'y':dict(min=-90,max=90,clamped=True,locked=True)};node['driven']=['z']
        converted=convert_pose(pose,target);values=converted['rotations']['l_forearm']
        self.assertLessEqual(abs(values[0]),5.000001);self.assertEqual(values[1:],[0,0]);self.assertTrue(any('movement limits' in w for w in converted['warnings']))
    def test_add_remove_save_restore_mixed_generation_scene(self):
        _,original=fixture(1,0);g9=target_rig();profiles={'g8m':original['rig'],'g9':g9};progress=lambda *_:None
        with tempfile.TemporaryDirectory() as folder,patch('editor.profile',side_effect=lambda root,id:profiles[id]):
            root=Path(folder);first=new_pose(root,'g8m');first['rotations']['lHand']=[10,20,30]
            added=operation(root,dict(editorOperation='add_mannequin',poses=[first],rigId='g9'),progress)
            self.assertEqual(added['selected'],2);a,b=added['poses'];self.assertEqual(a['rotations'],first['rotations']);self.assertEqual(a['translation'],first['translation'])
            self.assertEqual(b['rigId'],'g9');self.assertGreater(b['translation'][0],a['translation'][0]);self.assertNotIn('quality',b)
            loaded=operation(root,dict(editorOperation='load_draft',imageId=a['imageId']),progress);self.assertEqual(loaded['poses'],added['poses'])
            operation(root,dict(editorOperation='save_draft',imageId=a['imageId'],poses=[b]),progress)
            self.assertEqual(operation(root,dict(editorOperation='load_draft',imageId=a['imageId']),progress)['poses'],[b])
            self.assertEqual(len(pose_history(root)),2)
            members=added['poses']
            while len(members)<4:members=operation(root,dict(editorOperation='add_mannequin',poses=members,rigId='g9'),progress)['poses']
            with self.assertRaises(ValueError):operation(root,dict(editorOperation='add_mannequin',poses=members,rigId='g9'),progress)
    def test_converted_draft_and_reset_baseline_share_target_profile(self):
        _,original=fixture(1,0);g9=target_rig();progress=lambda *_:None
        with tempfile.TemporaryDirectory() as folder,patch('editor.profile',side_effect=lambda root,id:original['rig'] if id=='g8m' else g9):
            root=Path(folder);baseline=new_pose(root,'g8m');pose=copy.deepcopy(baseline);pose['rotations']['lForearmBend']=[30,20,10]
            result=operation(root,dict(editorOperation='convert_pose',pose=pose,poses=[pose],baseline=baseline,rigId='g9'),progress)
            self.assertEqual(result['pose']['imageId'],baseline['imageId']);self.assertEqual(result['baseline']['rigId'],'g9');self.assertNotEqual(result['pose']['rotations'],result['baseline']['rotations'])
            checked_poses(root,pose['imageId'],[result['pose']])
    def test_studio_requires_valid_source_provenance_and_neutral_has_no_confidence(self):
        _,pose=fixture(1,0);pose.update(origin='editor',studio=True,imageId='pose-'+'0'*32,studioSource=dict(imageId='a'*24,personId=1,personKey='key'))
        with patch('editor.profile',return_value=pose['rig']),patch('editor.read_json',return_value=[dict(id=1)]),patch('editor.identity',return_value='key'),patch('editor.cached_source',return_value={'version':2}):
            self.assertEqual(checked_poses(Path('temp'),pose['imageId'],[pose])[1],['key'])
            pose['studioSource']['personKey']='stale'
            with self.assertRaises(ValueError):checked_poses(Path('temp'),pose['imageId'],[pose])
            pose.pop('studioSource');pose['quality']={'detection':.99}
            with self.assertRaises(ValueError):checked_poses(Path('temp'),pose['imageId'],[pose])

if __name__=='__main__':unittest.main()
