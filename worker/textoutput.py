"""Export/apply accepted generated results using the existing native safeguards."""
import copy
import json
import re
import subprocess
import uuid
from pathlib import Path
from storage import read_json, atomic_json


def accepted(root, payload):
    from editor import same_profile
    from rigs import profile
    from daz import validate_pose
    key = payload.get('id', '')
    if not re.fullmatch(r'text-[a-f0-9]{32}', key): raise ValueError('Accept a generated result before exporting.')
    record = read_json(root/'data/text'/f'{key}.json')
    if not record or type(payload.get('actorId')) is not int: raise ValueError('Choose an accepted actor.')
    from textpose import signature
    if record.get('signature')!=signature({k:v for k,v in record.items() if k!='signature'}):raise ValueError('This saved result failed its integrity check. Restore a backup or generate it again.')
    actor = payload['actorId']; pose = next((p for p in record['poses'] if p['personId'] == actor), None)
    facial = next((e for e in record['expressions'] if e['actorId'] == actor), None)
    if not pose and not facial: raise ValueError('That actor is not part of this accepted result.')
    if pose:
        validate_pose(pose)
        if not same_profile(pose['rig'], profile(root, pose['rigId'])): raise ValueError('Body metadata changed. Refit this result before exporting.')
    if facial:
        import expression
        facial = expression.retarget(root, dict(rigId=facial['rigId'], source=facial['source'], options=dict(strength=1, regions={r: True for r in expression.REGIONS})))
    return pose, facial


def combined_script(pose, facial, profile, placement, config):
    from rigs import evaluated_channels, pose_channels, RIG_LABELS
    from daz import validate_pose, validate_placement
    validate_pose(pose); validate_placement(pose, placement)
    if pose['rigId'] != facial['rigId']: raise ValueError('Body and face must use the same selected generation.')
    pose = dict(pose, rotations=pose_channels(pose['rig'], pose['rotations']))
    config = dict(config, body=dict(pose=pose, evaluated=evaluated_channels(pose['rig'], pose['rotations']), placement=placement), expression=facial, profile=profile, rigId=pose['rigId'], label=RIG_LABELS[pose['rigId']], connect=False, zero=False)
    library = Path(__file__).with_name('body_transaction.dsa').read_text(encoding='utf-8')
    script = Path(__file__).with_name('expression_figure.dsa').read_text(encoding='utf-8')
    return '(function(){\n'+library+'\n'+script.replace('__POSESNAP_CONFIG__', json.dumps(config, ensure_ascii=True, allow_nan=False))+'\n}());'


def output(root, payload, progress, apply=False):
    from daz import duf, apply as apply_pose
    import expression
    pose, facial = accepted(root, payload)
    placement = payload.get('placement', 'floor')
    if placement not in ('keep', 'floor'): raise ValueError('Choose Keep scene position or Use preview position.')
    if not apply:
        document = duf(pose, placement) if pose else expression.duf(root, dict(expression=facial))
        if pose and facial: document['scene']['animations'] += expression.duf(root, dict(expression=facial))['scene']['animations']
        path = Path(payload['path']).with_suffix('.duf'); atomic_json(path, document); return dict(path=str(path))
    if not facial: return apply_pose(root, dict(payload, pose=pose, placement=placement), progress)
    if not pose: return expression.handoff(root, dict(payload, expression=facial), progress)
    executable = Path(payload['executable'])
    if not executable.is_file() or executable.name.lower() != 'dazstudio.exe': raise ValueError('Choose DAZStudio.exe in Settings first.')
    job = uuid.uuid4().hex; folder = root/'temp/daz'/job; folder.mkdir(parents=True)
    active = payload.get('_jobId', job)
    if not re.fullmatch(r'[A-Za-z0-9-]{1,79}', active): raise ValueError('Invalid DAZ job.')
    cancel = root/'temp/jobs'/f'{active}.cancel'; ack = folder/'ack.json'; status = folder/'status.json'
    config = dict(version=1, jobId=job, cancel=str(cancel).replace('\\', '/'), ack=str(ack).replace('\\', '/'), status=str(status).replace('\\', '/'))
    script = folder/'apply-generated.dsa'; script.write_text(combined_script(pose, facial, expression.profile(root, facial['rigId']), placement, config), encoding='utf-8')
    from daz_handoff import daz_running, wait_for_ack
    was_running = daz_running(executable) is True
    progress('Waiting for DAZ · body and expression share one Undo', 25)
    process = subprocess.Popen([str(executable), str(script)], cwd=executable.parent)
    return wait_for_ack(ack, cancel, status, job, executable, process, progress, was_running)
