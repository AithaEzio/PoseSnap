import copy, unittest
import numpy as np
from evidence import BODY_MAP, agreement, landmarks, project
from interaction import camera_translation, segment_distance, coordinate, projected, TARGET
from retarget import fk
from daz import duf

def fixture(person,x,height=180):
    nodes=[]
    def add(name,parent,center,end,kind='bone'):
        nodes.append(dict(id=name,parent=parent,center=center,end=end,type=kind,orientation=[0,0,0],order='XYZ',limits={}))
    add('figure',None,[0,0,0],[0,95,0],'figure');add('hip','figure',[0,95,0],[0,110,0])
    add('chestUpper','hip',[0,145,0],[0,155,0]);add('head','chestUpper',[0,height,0],[0,height+10,0])
    for side,sign in [('l',1),('r',-1)]:
        add(side+'ShldrBend','chestUpper',[sign*20,145,0],[sign*30,125,0]);add(side+'ForearmBend',side+'ShldrBend',[sign*30,125,0],[sign*40,110,0]);add(side+'Hand',side+'ForearmBend',[sign*40,110,0],[sign*45,108,0])
        add(side+'ThighBend','hip',[sign*10,95,0],[sign*10,50,0]);add(side+'Shin',side+'ThighBend',[sign*10,50,0],[sign*10,5,0]);add(side+'Foot',side+'Shin',[sign*10,5,0],[sign*10,0,10])
    rig=dict(id='g8m',label='Synthetic',sourceId='figure',nodes=nodes)
    pose=dict(version=1,rigId='g8m',label='Synthetic',personId=person,imageId='same',rig=rig,rotations={n['id']:[0,0,0] for n in nodes if n['type']=='bone'},translation=[0,0,0],warnings=[],handRefinement=True)
    positions=fk(rig,pose['rotations'])[1]
    aliases={'root':'hip','c_spine3':'chestUpper','c_head':'head','l_uparm':'lShldrBend','r_uparm':'rShldrBend','l_lowarm':'lForearmBend','r_lowarm':'rForearmBend','l_wrist':'lHand','r_wrist':'rHand'}
    names=list(aliases);sourcepoints=[(positions[n]/100).tolist() for n in aliases.values()]
    cam=[x,.8,4];focal=1000;size=[1200,900]
    evidence=[]
    for coco,options in TARGET.items():
        point=projected(positions[options[0]]+camera_translation(cam),focal,size)
        evidence.append(dict(coco=coco,mhr=BODY_MAP[coco],xy=point.tolist(),weight=.95))
    source=dict(version=2,imageId='same',personId=person,personKey=str(person),names=names,positions=sourcepoints,restPositions=sourcepoints,camera=[[focal,0,600],[0,focal,450],[0,0,1]],cameraTranslation=cam,imageSize=size,focalLength=focal,evidence=evidence)
    return source,pose

class EvidenceTests(unittest.TestCase):
    def test_coco_wrists_and_hips_use_mhr_keypoint_ids(self):
        self.assertEqual([BODY_MAP[i] for i in (9,10,11,12,15,16)],[62,41,9,10,13,14])
    def test_match_percentage_is_explicit_image_tolerance(self):
        points=np.zeros((70,2));evidence=[dict(mhr=i,xy=[0,0]) for i in (5,6,7,8)]
        points[8]=[51,0];result=agreement(points,evidence,1000)
        self.assertEqual(result['matched'],.75);self.assertEqual(result['count'],4)
    def test_no_percentage_for_inadequate_or_nonfinite_evidence(self):
        result=agreement(np.zeros((70,2)),[dict(mhr=5,xy=[0,0])],1000)
        self.assertIsNone(result['matched'])
        points=np.zeros((70,2));points[5]=[np.nan,0]
        result=agreement(points,[dict(mhr=i,xy=[0,0]) for i in (5,6,7,8)],1000)
        self.assertIsNone(result['matched'])
    def test_prompt_excludes_ambiguous_partner_joint_and_wrong_mask(self):
        person=dict(box=[0,0,100,100],keypoints=[[50,50,.9] for _ in range(17)])
        other=copy.deepcopy(person)
        self.assertFalse(landmarks(person,[other]))
        self.assertFalse(landmarks(person,mask=np.zeros((100,100))))
        self.assertEqual(len(landmarks(person,mask=np.ones((100,100)))),12)
    def test_camera_projection_and_axis_conversion_roundtrip(self):
        np.testing.assert_allclose(camera_translation([1,2,3]),[100,-200,-300])
        np.testing.assert_allclose(project([[0,0,0]],[1,2,4],1000,[1200,800]),[[850,900]])
        with self.assertRaises(ValueError):camera_translation([1,2,-3])

class InteractionTests(unittest.TestCase):
    def test_finite_segment_distance_crossing_parallel_and_endpoints(self):
        p=lambda x:np.array(x,dtype=float)
        self.assertEqual(segment_distance(p([0,0,0]),p([1,0,0]),p([.5,-1,0]),p([.5,1,0])),0)
        self.assertEqual(segment_distance(p([0,0,0]),p([1,0,0]),p([0,3,0]),p([1,3,0])),3)
        self.assertEqual(segment_distance(p([0,0,0]),p([1,0,0]),p([3,0,0]),p([4,0,0])),2)
    def test_shared_layout_retains_separation_and_mixed_rig_height(self):
        a,pa=fixture(1,-.5,180);b,pb=fixture(2,.5,170);pb['rigId']='g9'
        before=copy.deepcopy([pa,pb]);result=coordinate([a,b],[pa,pb])
        self.assertEqual([pa,pb],before)
        translations=np.array([p['translation'] for p in result['poses']])
        self.assertGreater(translations[1,0]-translations[0,0],70)
        self.assertLess(result['diagnostics']['maximumProxyOverlapCm'],.01)
        self.assertEqual(result['poses'][0]['layout']['id'],result['poses'][1]['layout']['id'])
        self.assertEqual(result['poses'][1]['rigId'],'g9')
    def test_shared_camera_and_sufficient_evidence_are_required(self):
        a,pa=fixture(1,-.5);b,pb=fixture(2,.5)
        b['camera'][0][0]=2000
        with self.assertRaises(ValueError):coordinate([a,b],[pa,pb])
        b['camera']=copy.deepcopy(a['camera']);b['evidence']=b['evidence'][:3]
        with self.assertRaises(ValueError):coordinate([a,b],[pa,pb])
    def test_close_contact_corrections_are_bounded_and_reduce_proxy_overlap(self):
        a,pa=fixture(1,-.18);b,pb=fixture(2,.18)
        result=coordinate([a,b],[pa,pb]);diagnostics=result['diagnostics']
        self.assertGreater(diagnostics['contacts'],0)
        self.assertLessEqual(diagnostics['maximumProxyOverlapCm'],diagnostics['initialProxyOverlapCm']+.01)
        for original,pose in zip((pa,pb),result['poses']):
            for node,values in pose['rotations'].items():
                self.assertTrue(np.all(np.abs(np.array(values)-original['rotations'][node])<=12.000001))
    def test_reference_duf_writes_identical_shared_translation(self):
        a,pa=fixture(1,-.5);b,pb=fixture(2,.5);poses=coordinate([a,b],[pa,pb])['poses']
        for pose in poses:
            animations=duf(pose,'reference')['scene']['animations']
            actual=[next(row['keys'][0][1] for row in animations if row['url'].endswith('translation/'+axis+'/value')) for axis in 'xyz']
            self.assertEqual(actual,pose['translation'])
        with self.assertRaises(ValueError):duf(pa,'reference')

if __name__=='__main__':unittest.main()
