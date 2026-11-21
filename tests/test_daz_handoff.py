"""Exercise session death, deadlines and acknowledgments without a DAZ scene."""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import daz_handoff as handoff

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.ack=self.root/'ack.json';self.cancel=self.root/'cancel';self.status=self.root/'status.json';self.clock=0
        self.launch=Mock();self.launch.poll.return_value=0;self.progress=Mock()
    def tick(self,seconds):self.clock+=seconds
    def wait(self,alive=True,**kwargs):
        with patch.object(handoff.time,'monotonic',side_effect=lambda:self.clock),patch.object(handoff.time,'sleep',side_effect=self.tick),patch.object(handoff,'daz_running',return_value=alive):
            return handoff.wait_for_ack(self.ack,self.cancel,self.status,'job',self.root/'DAZStudio.exe',self.launch,self.progress,**kwargs)
    def write_ack(self,**kwargs):self.ack.write_text(json.dumps(dict(version=1,jobId='job',success=True,**kwargs)))
    def test_acknowledged_success_takes_priority_over_session_exit(self):
        self.write_ack(zeroed=4);self.assertEqual(self.wait(False,was_running=True)['zeroed'],4);self.assertFalse(self.cancel.exists())
    def test_existing_session_death_stops_wait_immediately(self):
        with self.assertRaisesRegex(ValueError,'DAZ Studio closed'):self.wait(False,was_running=True)
        self.assertLess(self.clock,1);self.assertTrue(self.cancel.exists())
    def test_short_lived_launcher_exit_is_not_daz_session_exit(self):
        def tick(seconds):
            self.clock+=seconds
            if self.clock>=2:self.write_ack(zeroed=2)
        with patch.object(handoff.time,'monotonic',side_effect=lambda:self.clock),patch.object(handoff.time,'sleep',side_effect=tick),patch.object(handoff,'daz_running',return_value=True):
            self.assertEqual(handoff.wait_for_ack(self.ack,self.cancel,self.status,'job',self.root/'DAZStudio.exe',self.launch,self.progress)['zeroed'],2)
    def test_failed_launch_has_startup_grace_then_reports_closed(self):
        with self.assertRaisesRegex(ValueError,'DAZ Studio closed'):self.wait(False)
        self.assertGreaterEqual(self.clock,5);self.assertLess(self.clock,7);self.assertTrue(self.cancel.exists())
    def test_inaccessible_session_uses_bounded_deadline(self):
        with self.assertRaisesRegex(ValueError,'stopped waiting'):self.wait(None,timeout=3)
        self.assertLess(self.clock,4);self.assertTrue(self.cancel.exists())
    def test_cancelled_task_never_accepts_an_ack(self):
        self.write_ack();self.cancel.write_text('cancelled')
        with self.assertRaises(InterruptedError):self.wait()
    def test_failure_and_wrong_job_cancel_queued_work(self):
        for data in (dict(version=1,jobId='job',success=False,message='Locked driver'),dict(version=1,jobId='wrong',success=True),[]):
            with self.subTest(data=data):
                self.cancel.unlink(missing_ok=True);self.ack.write_text(json.dumps(data))
                with self.assertRaises(ValueError):self.wait()
                self.assertTrue(self.cancel.exists())
    def test_partial_ack_is_retried_and_phases_are_emitted_once(self):
        self.ack.write_text('{');self.status.write_text(json.dumps(dict(version=1,jobId='job',phase='snapshot')))
        def tick(seconds):
            self.clock+=seconds
            if self.clock>=.6:self.write_ack(zeroed=1)
        with patch.object(handoff.time,'monotonic',side_effect=lambda:self.clock),patch.object(handoff.time,'sleep',side_effect=tick),patch.object(handoff,'daz_running',return_value=True):
            self.assertEqual(handoff.wait_for_ack(self.ack,self.cancel,self.status,'job',self.root/'DAZStudio.exe',self.launch,self.progress)['zeroed'],1)
        self.progress.assert_called_once_with('Protecting body pose and identity',60)
    def test_process_inspection_is_read_only_and_recognizes_missing_daz(self):
        result=handoff.daz_running(self.root/'DAZStudio.exe');self.assertIn(result,(False,None))
    @unittest.skipUnless(handoff.os.name=='nt','Windows process enumeration')
    def test_process_inspection_recognizes_its_own_exact_executable(self):
        self.assertIs(handoff.daz_running(Path(sys.executable)),True)

if __name__=='__main__':unittest.main()
