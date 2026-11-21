"""Bounded support fitting and geometric diversity for Kimodo body proposals."""


def validate(value):
    if value is None or value == {}: return None
    if not isinstance(value, dict) or set(value) - {'version', 'weight', 'arms'}:
        raise ValueError('Unsupported body fitting goal.')
    if type(value.get('version', 1)) is not int or value.get('version', 1) != 1:
        raise ValueError('Unsupported body fitting goal version.')
    result = dict(version=1)
    if 'weight' in value:
        if value['weight'] not in ('l', 'r', 'both', 'air'):
            raise ValueError('Unknown weight-bearing state.')
        result['weight'] = value['weight']
    if 'arms' in value:
        arms = value['arms']
        if not isinstance(arms, dict) or set(arms) - {'l', 'r'} or any(v != 'waist' for v in arms.values()):
            raise ValueError('Unknown independent arm fitting goal.')
        result['arms'] = dict(arms)
    return result


def fit_support(pose, support, straight_knees=()):
    """Fit planted soles to a common plane, then let placement set floor Y."""
    import numpy as np
    from scipy.optimize import least_squares
    from measurements import target_points
    from studio import semantics
    planted=[s for s,state in support.items() if state!='air']
    if not planted:return
    def keys(side):return ('heel',) if support[side]=='heel' else ('bigtoe','smalltoe') if support[side]=='toe' else ('heel','bigtoe','smalltoe')
    points,_=target_points(pose)
    heights=[points[s+'_'+k][1] for s in planted for k in keys(s)]
    if max(heights)-min(heights)<.6:return
    mapping=semantics(pose['rig']);variables=[];start=[];low=[];high=[]
    for node in pose['rig']['nodes']:
        if node['id'] not in {mapping.get(s+'_'+k) for s in planted for k in ('thigh','shin','foot','toes')}|{s+'ThighBend' for s in planted}:continue
        for axis,key in enumerate('xyz'):
            lim=node['limits'].get(key,{})
            if lim.get('locked') or key in node.get('driven',[]):continue
            lo=lim.get('min',-180) if lim.get('clamped') else -180;hi=lim.get('max',180) if lim.get('clamped') else 180
            if hi-lo<1e-6:continue
            variables.append((node['id'],axis));start.append(pose['rotations'][node['id']][axis]);low.append(lo);high.append(hi)
    if not variables:raise ValueError('The requested soles cannot align with these locked joints.')
    originals={s:points[s+'_ankle'].copy() for s in planted};start=np.clip(start,low,high)
    def residual(values):
        for (node,axis),v in zip(variables,values):pose['rotations'][node][axis]=float(v)
        p,_=target_points(pose);errors=[]
        # Fixing this plane to the initial lowest sole point can require a leg
        # to extend beyond its length. Global Y placement follows this fit;
        # solve relative sole heights here without anchoring an unreachable Y.
        plane=np.mean([p[s+'_'+k][1] for s in planted for k in keys(s)])
        for side in planted:
            soles=[p[side+'_'+k][1] for k in keys(side)]
            errors.extend((np.array(soles)-plane)/.6)
            errors.extend((p[side+'_ankle'][[0,2]]-originals[side][[0,2]])/8)
            if side in straight_knees:
                # Planting the soles must not undo an explicit straight-leg
                # goal. Match segment directions without an acos singularity.
                upper=p[side+'_knee']-p[side+'_hip'];lower=p[side+'_ankle']-p[side+'_knee']
                errors.extend((upper/np.linalg.norm(upper)-lower/np.linalg.norm(lower))/np.deg2rad(2.))
        return np.r_[errors,(values-start)/80*.1]
    fit=least_squares(residual,start,bounds=(low,high),max_nfev=45)
    residual(fit.x)
    points,_=target_points(pose)
    heights=[points[s+'_'+k][1] for s in planted for k in keys(s)]
    if max(heights)-min(heights)>1.:raise ValueError('This pose could not plant both feet within 1 cm. Try another variation.')


def verify_support(pose):
    """Check a new pose's claims against the fixed floor, after all fitting."""
    from measurements import target_points
    if pose.get('bodyContacts'):
        from body_contacts import verify
        verify(pose)
        return
    support={r['side']:r['state'] for r in pose.get('footSupport',[])}
    if not support:return
    points,_=target_points(pose)
    both_air=all(support.get(side)=='air' for side in ('l','r'))
    for side,state in support.items():
        soles={key:float(points[side+'_'+key][1]) for key in ('heel','bigtoe','smalltoe')}
        lowest=min(soles.values())
        contact=abs(soles['heel']) if state=='heel' else max(abs(soles['bigtoe']),abs(soles['smalltoe'])) if state=='toe' else max(map(abs,soles.values()))
        air_min=.5 if pose.get('bodyGenerator',{}).get('provider')=='kimodo' else 14.95 if both_air else .5
        if lowest < -.05 or (state=='air' and lowest<air_min) or (state!='air' and abs(contact)>1.):
            raise ValueError('The fitted feet do not satisfy the requested floor support. Try another composition; the accepted result is kept.')


def distance(a, b):
    """Root-aligned major-joint diversity; camera/placement changes do not count."""
    import numpy as np
    from textpose import frame
    from studio import semantics
    wa,pa=frame(a);wb,pb=frame(b);ma=semantics(a['rig']);mb=semantics(b['rig'])
    keys=['head',*[s+'_'+k for s in ('l','r') for k in ('upperarm','forearm','hand','thigh','shin','foot')]]
    root_a=pa[ma['hip']];root_b=pb[mb['hip']]
    delta=np.array([wa[ma['hip']].T@(pa[ma[k]]-root_a)-wb[mb['hip']].T@(pb[mb[k]]-root_b) for k in keys])
    height=max(n['center'][1] for n in a['rig']['nodes'])-min(n['center'][1] for n in a['rig']['nodes'])
    return float(np.sqrt(np.mean(np.sum(delta*delta,axis=1)))/max(height,1))


def distinct(a, b):
    return distance(a,b)>=.03
