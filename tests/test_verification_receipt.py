"""Final source identity must stay bound even after checks have completed."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1]/'scripts/verify.py'
spec = importlib.util.spec_from_file_location('local_verification_entrypoint', path)
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


class VerificationReceiptTests(unittest.TestCase):
    def test_late_source_edit_revokes_success(self):
        report = dict(sourceBefore='original', passed=True)
        verification.finish_report(report, 'edited')
        self.assertFalse(report['passed'])
        self.assertIn('Source changed', report['error'])

    def test_unchanged_source_keeps_actual_result_and_prior_failure_reason(self):
        report = dict(sourceBefore='same', passed=False, error='Worker failure')
        verification.finish_report(report, 'same')
        self.assertFalse(report['passed'])
        self.assertEqual(report['error'], 'Worker failure')
        report = dict(sourceBefore='same', passed=True)
        verification.finish_report(report, 'same')
        self.assertTrue(report['passed'])

    def test_incomplete_work_cannot_become_success(self):
        report = dict(sourceBefore='same')
        verification.finish_report(report, 'same')
        self.assertFalse(report['passed'])

    def test_changed_build_cannot_reach_packaging_with_old_test_identity(self):
        with self.assertRaisesRegex(RuntimeError,'Source changed during building'):
            verification.require_frozen(dict(sourceBefore='tested'),'different-build','building')
        verification.require_frozen(dict(sourceBefore='tested'),'tested','building')


if __name__ == '__main__':
    unittest.main()
