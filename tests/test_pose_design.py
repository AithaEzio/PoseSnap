import copy
import tempfile
import unittest
from pathlib import Path
from storage import atomic_json,read_json
import textpose
import pose_design

ROOT=Path(__file__).resolve().parents[1]


class PoseDesignTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'temp/design-tests';base.mkdir(parents=True,exist_ok=True)
        self.folder=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name)
        atomic_json(self.root/'data/rigs/g8f.json',read_json(ROOT/'tests/fixtures/target-fit/g8f.json'))
        self.payload=dict(output='pose',mode='create',prompt='A happy pose',actors=[dict(id=1,rigId='g8f')],creative=True,candidateCount=3,variationSeed=0)

    def test_camera_rotation_and_translation_do_not_count_as_diversity(self):
        original=textpose.neutral(self.root,'g8f','pose-'+'0'*32,1);moved=copy.deepcopy(original)
        moved['translation']=[50,30,-90];moved['rootRotation']=[0,90,0]
        self.assertFalse(pose_design.distinct(original,moved))

    def test_invalid_or_nonfinite_design_and_generation_parameters_rejected(self):
        for value in ({'scale':2},{'lean':float('nan')},{'twist':31},{'arms':{'l':'teleport'}},{'choice':'happy-900'}):
            with self.assertRaises(ValueError):pose_design.validate(value)
        for field,value in (('variationSeed',-1),('variationSeed',True),('candidateCount',400),('style','unsafe')):
            with self.assertRaises(ValueError):textpose.task(dict(self.payload,**{field:value}))
