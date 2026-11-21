"""Independent annotations only: model predictions are never ground truth."""
import json
from pathlib import Path
import numpy as np

STAGES=('baseline','wholebody','detail','final','mediapipe-heavy')
def evaluate(manifest,base):
    base=Path(base).resolve()
    cases=manifest.get('cases',[]);rows=[];categories=set();identities=set();failures=[];known_interactions=0
    for case in cases:
        if case['imageDigest'] in identities:raise ValueError('Each held-out image must have a unique digest.')
        identities.add(case['imageDigest']);categories.add(case['category'])
        truth=case['people'];metrics={}
        if case.get('review') and not all(case['review'].get(key) is True for key in ('category','ownership')):
            failures.append(case['id']+': category or person ownership review is incomplete')
        if len(truth)>1 and case['category'] in ('mannequin-render','genesis-render'):
            if case.get('relativeDepthCm') is None or not case.get('contacts'):
                failures.append(case['id']+': known interaction render lacks depth/contact truth')
            else:known_interactions+=1
        for stage in STAGES:
            filename=case.get('runs',{}).get(stage)
            if not filename:continue
            path=(base/filename).resolve()
            if not path.is_relative_to(base):raise ValueError('Prediction paths must stay inside the benchmark folder.')
            prediction=json.loads(path.read_text(encoding='utf-8'))
            people={p['personId']:p for p in prediction['people']};errors={k:[] for k in ('body','hand','foot')};observed=total=0
            for person in truth:
                if not np.isfinite(person['heightPx']) or person['heightPx']<=0:raise ValueError('Annotated person height must be positive and finite.')
                actual=people.get(person['personId'],{}).get('points',{})
                for point in person['landmarks']:
                    if not point.get('visible',True):continue
                    if np.asarray(point['xy']).shape!=(2,) or not np.isfinite(point['xy']).all():raise ValueError('Ground-truth landmarks must have two finite coordinates.')
                    if point['region'] not in ('body','l_hand','r_hand','l_foot','r_foot'):raise ValueError('Unsupported ground-truth region.')
                    xy=actual.get(point['name']);total+=1
                    valid=xy is not None and np.asarray(xy).shape==(2,) and np.isfinite(xy).all()
                    # Missing predictions are penalised, not silently omitted.
                    error=float(np.linalg.norm(np.asarray(xy)-point['xy'])) if valid else person['heightPx']
                    observed+=int(valid);region='body' if point['region']=='body' else 'hand' if point['region'].endswith('hand') else 'foot'
                    errors[region].append(error/person['heightPx'])
            metrics[stage]={k:float(np.median(v)) if v else None for k,v in errors.items()}
            metrics[stage]['coverage']=observed/max(1,total)
            if stage=='final':
                if case.get('relativeDepthCm') is not None:
                    ids=[p['personId'] for p in truth]
                    roots=[people.get(i,{}).get('rootCm') for i in ids[:2]]
                    if len(ids)<2 or not np.isfinite(case['relativeDepthCm']):raise ValueError('Relative-depth truth requires two people and a finite distance.')
                    z=[r[2] for r in roots if r is not None and np.asarray(r).shape==(3,) and np.isfinite(r).all()]
                    if len(z)!=2:failures.append(case['id']+': root-depth prediction missing or invalid')
                    elif abs(z[1]-z[0]-case['relativeDepthCm'])>5:failures.append(case['id']+': relative depth exceeds 5 cm')
                for contact in case.get('contacts',[]):
                    predicted=prediction.get('contactGapsCm',{}).get(contact['id'])
                    expected=contact.get('gapCm',0)
                    if not np.isfinite(expected) or expected<0:raise ValueError('Contact truth must be finite and non-negative.')
                    if predicted is None or not np.isfinite(predicted) or predicted<0 or abs(predicted-expected)>2:failures.append(case['id']+': contact gap exceeds 2 cm or is missing/invalid')
                checks=prediction.get('checks',{})
                if checks.get('personSwaps',1) or checks.get('reversedHandsFeet',1):failures.append(case['id']+': ownership/orientation checks missing or failed')
                if checks.get('footSupportCorrect') is not True:failures.append(case['id']+': foot support not verified')
                channel_error=checks.get('maximumDazChannelErrorDegrees',float('inf'))
                if not isinstance(channel_error,(int,float)) or not np.isfinite(channel_error) or not 0<=channel_error<=.1:failures.append(case['id']+': DAZ channel agreement not verified')
        rows.append(dict(id=case['id'],metrics=metrics))
    summary={}
    for stage in STAGES:
        summary[stage]={region:float(np.median(values)) if (values:=[r['metrics'][stage][region] for r in rows if stage in r['metrics'] and r['metrics'][stage][region] is not None]) else None for region in ('body','hand','foot','coverage')}
    paired={}
    for region in ('body','hand','foot'):
        pairs=[(r['metrics']['baseline'][region],r['metrics']['final'][region]) for r in rows if 'baseline' in r['metrics'] and 'final' in r['metrics'] and r['metrics']['baseline'][region] is not None and r['metrics']['final'][region] is not None]
        paired[region]=dict(count=len(pairs),ratio=float(np.median([1. if before<1e-6 and after<1e-6 else after/max(before,1e-6) for before,after in pairs])) if pairs else None)
    required={'interaction-photo','mannequin-render','single-person','genesis-render'}
    if len(cases)<40:failures.append('At least 40 independently annotated held-out references are required')
    if not required<=categories:failures.append('Interaction photos, mannequin renders, single-person controls and Genesis renders are required')
    if not known_interactions:failures.append('At least one known interaction render with independent depth/contact truth is required')
    if not all(all(stage in r['metrics'] for stage in ('baseline','wholebody','detail','final')) for r in rows):failures.append('Every added stage must be compared on every reference')
    for region,limit in (('hand',.75),('foot',.75),('body',1.05)):
        if paired[region]['count']<20 or paired[region]['ratio'] is None or paired[region]['ratio']>limit:failures.append(region+' accuracy target not met or evidence is insufficient')
    if not any('mediapipe-heavy' in r['metrics'] for r in rows):failures.append('Isolated MediaPipe Heavy comparison is missing')
    return dict(version=1,referenceCount=len(cases),passed=not failures,summary=summary,paired=paired,failures=sorted(set(failures)),cases=rows)

def predictions(result):
    """Convert authoritative target results into the neutral comparison format."""
    poses=result.get('poses',[result]);people=[]
    for pose in poses:
        from measurements import target_points,project_target
        if not pose.get('referenceCamera'):raise ValueError('A retained reference camera is required for target measurements.')
        points,_=target_points(pose)
        people.append(dict(personId=pose['personId'],rootCm=pose['translation'],points={name:project_target(point,pose['referenceCamera']).tolist() for name,point in points.items()}))
    return dict(people=people,contactGapsCm={c['id']:c['gapCm'] for c in result.get('diagnostics',{}).get('contactGaps',[])})
