import copy, tempfile, unittest
from pathlib import Path
import numpy as np
from instances import identity, cached_source, distinct_people, mask_prompts, mask_quality
from storage import atomic_json

def person(x=0, score=.9):
    return dict(id=1,box=[0,0,300,1000],score=score,detector='rtmo-body7',detectionVersion=3,
        keypoints=[[x+60+(i%2)*45,60+i*48,.95] for i in range(17)])

class InstanceTests(unittest.TestCase):
    def test_nested_partial_duplicate_keeps_the_complete_observed_body(self):
        import json
        data=json.loads((Path(__file__).parent/'fixtures/partial-body-detection.json').read_text())
        kept=distinct_people(data['single'])
        self.assertEqual(len(kept),1)
        self.assertGreater(kept[0]['box'][3]-kept[0]['box'][1],180)
        self.assertEqual(len(distinct_people(data['pair'])),2)
        shifted=copy.deepcopy(data['single'][1])
        for point in shifted['keypoints']:point[0]+=35
        self.assertEqual(len(distinct_people([data['single'][0],shifted])),2)

    def test_same_boxes_with_distinct_skeletons_are_preserved(self):
        self.assertEqual(len(distinct_people([person(),person(120,.4)])),2)
    def test_repeated_skeleton_is_one_person(self):
        self.assertEqual(len(distinct_people([person(),person(2,.7)])),1)
    def test_confidence_alone_does_not_change_identity(self):
        self.assertEqual(identity(person()),identity(person(score=.5)))
    def test_context_and_landmarks_invalidate_the_source(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'temp') as temp:
            folder=Path(temp);p=person()
            atomic_json(folder/'solve-1.json',dict(version=2,personKey=identity(p)))
            self.assertIsNotNone(cached_source(folder,p))
            for key,value in [('contextKey','new partner'),('box',[1,0,300,1000]),('keypoints',person(3)['keypoints'])]:
                changed=copy.deepcopy(p);changed[key]=value
                self.assertIsNone(cached_source(folder,changed))
    def test_legacy_combined_source_is_never_reused(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'temp') as temp:
            folder=Path(temp);atomic_json(folder/'solve-1.json',dict(personId=1))
            self.assertIsNone(cached_source(folder,person()))
    def test_old_extraction_version_needs_camera_and_evidence_recompute(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'temp') as temp:
            folder=Path(temp);p=person();atomic_json(folder/'solve-1.json',dict(version=1,personKey=identity(p)))
            self.assertIsNone(cached_source(folder,p))
    def test_corrupt_source_can_be_recomputed(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'temp') as temp:
            folder=Path(temp);(folder/'solve-1.json').write_text('{broken',encoding='utf-8')
            self.assertIsNone(cached_source(folder,person()))
    def test_negative_prompts_are_other_anatomy_not_box_midpoints(self):
        own,other=person(),person(120)
        positive,negative=mask_prompts(own,[other])
        self.assertTrue(positive);self.assertTrue(negative)
        self.assertNotIn([150,500],negative)
        self.assertTrue(all(list(p) in [k[:2] for k in other['keypoints']] for p in negative))
    def test_empty_or_merged_mask_is_rejected(self):
        positive=[[10,10],[12,12]];negative=[[30,30]]
        self.assertFalse(mask_quality(np.zeros((50,50)),positive,negative))
        self.assertFalse(mask_quality(np.ones((50,50)),positive,negative))
        mask=np.zeros((50,50));mask[:20,:20]=1
        self.assertTrue(mask_quality(mask,positive,negative))

if __name__=='__main__':unittest.main()
