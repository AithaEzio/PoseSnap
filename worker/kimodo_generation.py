"""Free-form Kimodo body descriptions with the existing checked static-pose workflow."""
import copy
import hashlib
from itertools import combinations
from pathlib import Path
import re
import time
import numpy as np
from instructions import negated


def explicit_body(text):
    """Literal actor-relative goals, checked independently of either encoder."""
    from textconstraints import body_clauses
    goals = []; weight = None
    for clause in body_clauses(text):
        if negated(clause) or re.search(r"\b(?:slightly|half|degrees?)\b", clause): continue
        for part in ('head', 'torso'):
            for direction in ('left', 'right'):
                named = r'(?:(?:the|her|his|their)\s+)?'+part
                turn = r'(?:turn(?:ed|s)?|fac(?:e[sd]?|ing))'
                toward = r'\s+(?:(?:to|toward|towards)\s+(?:the\s+)?)?'
                if re.search(r'\b(?:'+named+r'\s+(?:(?:is|stays?|remains?)\s+)?'+turn+toward+direction+r'|turn\s+'+named+toward+direction+r')\b', clause):
                    goals.append(dict(part=part, movement='turn_'+direction, amount=1.))
            for direction in ('forward', 'back'):
                if re.search(r'\b(?:'+part+r'\s+lean(?:s|ing)?\s+'+direction+r'|lean\s+(?:the\s+)?'+part+r'\s+'+direction+r')\b', clause):
                    goals.append(dict(part=part, movement='lean_'+direction, amount=.5))
            if re.search(r'\b'+part+r'\s+(?:(?:is|stays?)\s+)?(?:upright|straight)\b', clause):
                goals.append(dict(part=part, movement='upright', amount=1.))
        match = re.search(r'\bweight\s+(?:rests?\s+)?on\s+(?:(?:the|her|his|their)\s+)?(left|right)\s+(?:leg|foot)\b', clause)
        if match:
            side = match[1][0]
            if weight and weight != side: raise ValueError('Choose one weight-bearing leg.')
            weight = side
    by_part = {}
    for goal in goals:
        if goal['part'] in by_part and by_part[goal['part']] != goal: raise ValueError('Choose one final direction for the '+goal['part']+'.')
        by_part[goal['part']] = goal
    return list(by_part.values()), weight


def plan(root, payload, context, interpreter, progress):
    import textpose
    from textconstraints import enforce, preflight, actor_text
    from kimodo_runtime import eligible
    textpose.task(payload)
    if not eligible(payload): raise ValueError('Kimodo needs one or two body actors.')
    checked = preflight(payload)
    if checked: return checked
    intent = textpose.basic_intent(payload)
    if intent['status'] != 'plan': return intent
    intent=copy.deepcopy(intent)
    for row in intent['actors']:
        text=actor_text(payload['prompt'].lower(),row['id'],len(intent['actors']))
        try: axial,weight=explicit_body(text)
        except ValueError as error:return dict(status='clarify',message=str(error)+' Your accepted result is kept.')
        row['recipe']='kimodo'
        row['bodyDescription']=payload['prompt'].strip()
        row.pop('design',None)
        row['changes']=[c for c in row['changes'] if c['part'] not in {g['part'] for g in axial}]+axial
        if weight:row['design']=dict(version=1,weight=weight)
    intent=enforce(textpose.validate_intent(intent,payload),payload)
    if intent['status']!='plan':return intent
    for row in intent['actors']:
        if row['preserve']:
            return dict(status='clarify',message='Text to Pose creates a new body pose. Open your accepted pose in Pose Studio to edit selected joints.')
        for change in row['changes']:
            if change['part'].endswith(('_leg','_foot')) and change['movement']=='raise' and change['amount']>=.9:row['support'][change['part'][0]]='air'
        from soma import airborne_request
        if airborne_request(actor_text(payload['prompt'],row['id'],len(intent['actors']))):row['support']=dict(l='air',r='air')
    intent['assumptions']=[*intent.get('assumptions',[])[:3], 'Kimodo generates the body. Optional hand shapes are approximate rule-based estimates; facial controls stay unchanged.', 'Refine generated joints in Pose Studio. Scene contacts use conservative geometry.']
    return textpose.validate_intent(intent,payload)


def generate(root, payload, intent, runtime, progress):
    import textpose
    from soma import shortlist,snapshot,frame_scores
    from pose_design import distance
    from textconstraints import actor_text
    from body_contacts import kind
    intent=textpose.validate_intent(intent,payload)
    if intent['status']!='plan':return dict(intent=intent)
    variations=textpose.variation_sources(root,payload)
    count=payload.get('candidateCount',3) if payload.get('creative') else 1
    seed=payload.get('variationSeed',0);seeds=[(seed+i*104729)%2**32 for i in range(count)]
    style=payload.get('style','natural');start=time.monotonic()
    actor_candidates=[];directions=[]
    for actor,row in zip(payload['actors'],intent['actors']):
        direction=actor_text(row['bodyDescription'],row['id'],len(intent['actors'])).strip() or 'A person stands naturally.'
        if intent['interaction']!='none' and len(direction)<35:
            direction={'handhold':'A person stands naturally and reaches one arm sideways.', 'front_hug':'A person leans slightly forward for a hug.', 'side_hug':'A person stands casually with one arm reaching sideways.', 'shoulder':'A person stands naturally and reaches one arm forward.'}[intent['interaction']]
        from body_profiles import direction as compile_direction
        direction=compile_direction(direction,style)
        directions.append(direction)
        clips=runtime.clips(direction,seeds,progress)
        candidates=[]
        for path in clips['clips']:
            actual=Path(path).resolve();actual.relative_to((root/'temp/kimodo').resolve())
            with np.load(actual,allow_pickle=False) as packed:clip={key:packed[key] for key in packed.files}
            clip_hash=hashlib.sha256(actual.read_bytes()).hexdigest()
            scores=frame_scores(clip,direction,row)
            frames=shortlist(clip,direction,2 if len(seeds)==3 else 6,row)
            for index in frames:
                try:
                    body=snapshot(root,actor['rigId'],clip,index,actor=actor['id'],prompt=direction)
                    body['bodyGenerator'].update(sourceClip=str(actual.relative_to(root)),sourceClipSha256=clip_hash)
                    body['bodyGenerator']['selectionScore']=scores.get(index,0.)
                    candidates.append(body)
                except ValueError:continue
        if not candidates:raise ValueError('Kimodo found no valid '+kind(direction)+' snapshot for Person '+str(actor['id'])+'. Your accepted result is kept.')
        actor_candidates.append(candidates)
    records=[];rejected=[];repeated=0
    attempts=min(6,max(map(len,actor_candidates)))
    for number in range(attempts):
        bodies=[copy.deepcopy(rows[number%len(rows)]) for rows in actor_candidates]
        try:
            record=textpose._generate_one(root,payload,copy.deepcopy(intent),progress,body_seeds=bodies)
            record['generation']['bodyDirections']=directions
            record['generation']['nativeConstraints']=False
            record['signature']=textpose.signature({k:v for k,v in record.items() if k!='signature'})
            from storage import atomic_json
            atomic_json(root/'temp/text'/f"{record['id']}.json",record)
            def gap(a,b):return max((distance(x,y)/.03 for x,y in zip(a['poses'],b['poses'])),default=0.)
            if any(gap(record,previous)<1. for previous in variations):
                repeated+=1
                continue
            if all(gap(record,previous)>=1. for previous in records):records.append(record)
        except ValueError as error:rejected.append(str(error))
    if not records:
        if repeated:raise ValueError('Kimodo found no new distinct choices in this batch. Try More like this again or adjust the direction. Your current preview and accepted result are kept.')
        raise ValueError('Kimodo could not fit a valid scene. '+(rejected[0] if rejected else 'Try another direction.')+' Your accepted result is kept.')
    def spread(group):
        pairs=list(combinations(group,2))
        body=[max(distance(x,y) for x,y in zip(a['poses'],b['poses']))/.03 for a,b in pairs]
        return min(body,default=0),sum(body)
    chosen=list(max(combinations(records,min(count,len(records))),key=spread))
    chosen.sort(key=lambda r:sum(p['bodyGenerator']['selectionScore'] for p in r['poses']),reverse=True)
    runtime.timings['totalGenerationSeconds']=time.monotonic()-start
    progress('Kimodo preview ready · Apply keeps this result',100)
    return dict(chosen[0],alternatives=chosen,choiceDiagnostics=dict(requested=count,returned=len(chosen),attempted=attempts,validDistinct=len(records),excludedPrevious=repeated,rejected=rejected))
