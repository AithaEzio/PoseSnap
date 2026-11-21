"""One offline verification entrypoint. No model inference or live DAZ mutation."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def finish_report(report, source_after):
    report['finished'] = datetime.now(timezone.utc).isoformat()
    report['sourceAfter'] = source_after
    report.setdefault('passed', False)
    # A source edit during final resource accounting must invalidate the receipt
    # too. Packaging independently checks source identity against the binary.
    if source_after != report['sourceBefore']:
        report['passed'] = False
        message = 'Source changed during verification. Freeze it and rerun before packaging.'
        report['error'] = '; '.join(value for value in (report.get('error'), message) if value)


def require_frozen(report,source_after,phase):
    if source_after!=report['sourceBefore']:
        raise RuntimeError('Source changed during '+phase+'. Freeze it and rerun checks before packaging.')


def worker_tests(out):
    sandbox = out/'unittest'
    sandbox.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = tempfile.tempdir = str(sandbox)
    sys.path[:0] = [str(ROOT/'worker'), str(ROOT/'tests')]
    suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'), pattern='test_*.py')
    with (out/'worker.log').open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    return {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
            'skipped': [{'test': str(t), 'reason': reason} for t, reason in result.skipped], 'passed': result.wasSuccessful()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('temp/verification')/datetime.now().strftime('%Y%m%d-%H%M%S'))
    parser.add_argument('--budget', type=Path, required=True, help='An authorised linked development ledger; never resets GPU use')
    parser.add_argument('--skip-native', action='store_true')
    parser.add_argument('--build-release', action='store_true')
    parser.add_argument('--package', metavar='UNIQUE_LABEL')
    parser.add_argument('--reuse-stage',type=Path,help='Reuse verified unchanged package files without merging distributions')
    args = parser.parse_args()
    if args.reuse_stage and not args.package:
        parser.error('--reuse-stage requires --package')
    os.chdir(ROOT)
    out = args.out.resolve()
    if not out.is_relative_to((ROOT/'temp').resolve()) or out.exists():
        raise ValueError('Use a new verification directory inside temp')
    out.mkdir(parents=True)
    sys.path.insert(0, str(ROOT/'training'))
    from pilot_budget import Budget
    sys.path.insert(0, str(Path(__file__).parent))
    from package import app_version, source_identity
    budget = Budget(args.budget)
    report = {'version': 1, 'started': datetime.now(timezone.utc).isoformat(), 'applicationVersion': app_version(ROOT),
              'sourceBefore': source_identity(ROOT)['sha256'], 'checks': [], 'liveDaz': 'excluded',
              'gpuInference': 'not run', 'unverified': ['live DAZ', 'signing/public publishing', 'other hardware/Windows versions']}

    def run(name, command):
        started = time.monotonic()
        with (out/(name+'.log')).open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            while True:
                try:
                    code = process.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    try:
                        budget.check()
                    except Exception:
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=log, stderr=subprocess.STDOUT)
                        raise
        report['checks'].append({'name': name, 'exitCode': code, 'seconds': time.monotonic()-started, 'log': name+'.log'})
        if code:
            raise RuntimeError(name+' failed; see '+str(out/(name+'.log')))
        budget.check()

    try:
        with budget.session('offline release verification', gpu=False):
            # Reserve growth before compiling/staging; actual usage is checked between and during commands.
            previous = ROOT/'src-tauri/target/release/build-receipt.json'
            native_unchanged = False
            if previous.is_file():
                prior = json.loads(previous.read_text(encoding='utf-8'))['source']['files']
                current = source_identity(ROOT)['files']
                native_unchanged = all(prior.get(k) == v for k, v in current.items() if k.startswith('src-tauri/'))
            reserve = ((384 if native_unchanged else 1536) if args.build_release else 256)*1024**2 + (1152*1024**2 if args.package else 0)
            report['forecast'] = {'nativeInputsUnchanged':native_unchanged,'additionalReserveBytes': reserve, 'currentAdditionalBytes': budget.data['additionalBytes'],
                                  'remainingStorageBytes': budget.data['storageLimitBytes']-budget.data['additionalBytes']}
            if budget.data['additionalBytes']+reserve > budget.data['storageLimitBytes'] or shutil.disk_usage(ROOT).free < reserve:
                raise ValueError('Forecast exceeds the authorised storage or disk headroom')
            npm = shutil.which('npm.cmd')
            if not npm:
                raise ValueError('Node/npm are development prerequisites, not portable runtime dependencies')
            for name, task in [('frontend-check', 'check'), ('frontend-tests', 'test'), ('frontend-build', 'build')]:
                run(name, [npm, 'run', task])
            started = time.monotonic()
            result = worker_tests(out)
            report['checks'].append({'name': 'worker', **result, 'seconds': time.monotonic()-started, 'log': 'worker.log'})
            if not result['passed']:
                raise RuntimeError('Worker tests failed')
            if not args.skip_native:
                run('native-tests', ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'scripts/check-native.ps1'])
                report['unverified'].append('Native ignored tests: public-source HEAD requests and full installed GPU-workspace verification are separate opt-in checks')
            else:
                report['unverified'].append('Native tests explicitly skipped')
            require_frozen(report,source_identity(ROOT)['sha256'],'verification')
            if args.build_release:
                run('release-build', ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'scripts/build.ps1'])
            require_frozen(report,source_identity(ROOT)['sha256'],'building')
            if args.package:
                command=[sys.executable, '-I', '-B', 'scripts/package.py', '--label', args.package, '--zip']
                if args.reuse_stage:command += ['--reuse-stage',str(args.reuse_stage)]
                run('package', command)
            report['passed'] = True
    except Exception as error:
        report.update(passed=False, error=str(error))
    finally:
        finish_report(report, source_identity(ROOT)['sha256'])
        (out/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'receipt': str(out/'verification.json'), 'error': report.get('error')}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
