"""Local rig metadata only. No content-library or Genesis mesh access."""
import copy, math, re
from functools import lru_cache
from pathlib import Path
from storage import atomic_json, read_json

RIG_IDS = ('g8f', 'g8m', 'g9')
RIG_LABELS = {'g8f':'Genesis 8 Female','g8m':'Genesis 8 Male','g9':'Genesis 9'}
FACIAL_PARTS = ('eye','face','jaw','tongue','teeth','brow','lip','labial','mouth','cheek','nose','ear','chin','squint','nostril','infraorbital')

def pose_bone(node):
    """Body posing excludes expression controls and passive pectoral correctives."""
    name=node['id'].lower()
    facial=any(part in name for part in FACIAL_PARTS) and 'forearm' not in name
    return node['type']=='bone' and not facial and 'pectoral' not in name

def pose_channels(rig,values):
    """Keep legacy all-bone drafts readable without exporting their passive zeros."""
    allowed={node['id'] for node in rig['nodes'] if pose_bone(node)}
    return {name:angles for name,angles in values.items() if name in allowed}

def channel_url(url):
    match=re.search(r'#([^?]+)\?rotation/([xyz])(?:/value)?$',url)
    if not match:raise ValueError('Unsupported rig formula channel: '+url)
    return match.group(1), 'xyz'.index(match.group(2))

def evaluated_channels(rig, values):
    """Evaluate the base rig's rotation ERCs, including Genesis 9 twist helpers."""
    grouped={};cache={};active=set()
    for formula in rig.get('formulas',[]):
        key=channel_url(formula['output']);grouped.setdefault(key,[]).append(formula)
    def resolve(key):
        if key in cache:return cache[key]
        if key in active:raise ValueError('Cyclic rig rotation formula')
        active.add(key);base=values.get(key[0],[0.,0.,0.])[key[1]];product=1.
        for formula in grouped.get(key,[]):
            stack=[]
            for operation in formula['operations']:
                if operation['op']=='push':stack.append(resolve(channel_url(operation['url'])) if 'url' in operation else float(operation['val']))
                elif operation['op'] in ('mult','add') and len(stack)>=2:
                    b=stack.pop();a=stack.pop();stack.append(a*b if operation['op']=='mult' else a+b)
                else:raise ValueError('Unsupported rig rotation formula operation')
            if len(stack)!=1:raise ValueError('Invalid rig rotation formula')
            if formula.get('stage','sum')=='sum':base+=stack[0]
            elif formula['stage']=='mult':product*=stack[0]
            else:raise ValueError('Unsupported rig formula stage')
        active.remove(key);cache[key]=base*product;return cache[key]
    return {n['id']:[resolve((n['id'],i)) for i in range(3)] for n in rig['nodes']}


def validate_profile(rig, rig_id):
    if rig_id not in RIG_IDS or not isinstance(rig,dict) or rig.get('id')!=rig_id or rig.get('version') not in (3,4):
        raise ValueError('Unsupported rig metadata. Reconnect the selected figure in DAZ Studio.')
    nodes=rig.get('nodes',[]);ids={n.get('id') for n in nodes}
    required={'hip','lHand','rHand','lShldrBend','rShldrBend'} if rig_id!='g9' else {'hip','l_hand','r_hand','l_upperarm','r_upperarm'}
    if len(ids)!=len(nodes) or not required.issubset(ids):
        raise ValueError('Selected figure has an incomplete Genesis rig.')
    for node in nodes:
        if not isinstance(node.get('id'),str) or not node['id'] or len(node['id'])>128 or node.get('parent') not in ids|{None}:
            raise ValueError('Invalid rig hierarchy')
        if node.get('order') not in ('XYZ','XZY','YXZ','YZX','ZXY','ZYX'):
            raise ValueError('Unsupported rig rotation order')
        for key in ('center','end','orientation'):
            values=node.get(key,[])
            if len(values)!=3 or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in values):
                raise ValueError('Invalid rest transform')
        for limit in node.get('limits',{}).values():
            if any(not isinstance(limit.get(k),(int,float)) or not math.isfinite(limit[k]) for k in ('min','max')):
                raise ValueError('Invalid rotation limits')
    roots=[n for n in nodes if n.get('parent') is None]
    if len(roots)!=1:raise ValueError('Invalid rig root')
    visited=set()
    for node in nodes:
        ancestry=set();current=node
        while current.get('parent') is not None:
            if current['id'] in ancestry:raise ValueError('Cyclic rig hierarchy')
            ancestry.add(current['id']);current=next(n for n in nodes if n['id']==current['parent'])
        visited.add(node['id'])
    for formula in rig.get('formulas',[]):
        if channel_url(formula['output'])[0] not in ids:raise ValueError('Invalid formula output')
        for op in formula['operations']:
            if 'url' in op and channel_url(op['url'])[0] not in ids:raise ValueError('Invalid formula input')
            if 'val' in op and (not isinstance(op['val'],(int,float)) or not math.isfinite(op['val'])):raise ValueError('Invalid formula constant')
    evaluated_channels(rig,{})
    return rig

def cache_profile(root, rig, rig_id):
    validate_profile(rig,rig_id)
    rig=dict(rig,version=4,label=RIG_LABELS[rig_id],metadataSource='daz-selection')
    rig.pop('source',None)
    atomic_json(root/'data/rigs'/(rig_id+'.json'),rig)
    return rig

@lru_cache(maxsize=1)
def _defaults():
    data=read_json(Path(__file__).with_name('default-rigs.json'))
    if not isinstance(data,dict) or data.get('version')!=1 or set(data.get('profiles',{}))!=set(RIG_IDS):
        raise ValueError('Built-in Genesis rig metadata is missing or invalid. Repair the PoseSnap application files.')
    return {rig_id:validate_profile(rig,rig_id) for rig_id,rig in data['profiles'].items()}


def default_profile(rig_id):
    if rig_id not in RIG_IDS:raise ValueError('Unsupported Genesis generation')
    # Fitting and editing may annotate a rig; never mutate the shared defaults.
    return copy.deepcopy(_defaults()[rig_id])


def profile(root, rig_id):
    if rig_id not in RIG_IDS:raise ValueError('Unsupported Genesis generation')
    path=root/'data/rigs'/(rig_id+'.json')
    rig=read_json(path)
    if not rig:return default_profile(rig_id)
    validate_profile(rig,rig_id)
    if rig.get('version')==3 or 'source' in rig:
        rig=dict(rig,version=4,metadataSource=rig.get('metadataSource','legacy-cache'))
        rig.pop('source',None)
        atomic_json(path,rig)
    return rig

def available_profiles(root):
    available=[]
    for rig_id in RIG_IDS:
        try:profile(root,rig_id);available.append(rig_id)
        except (ValueError,OSError,KeyError,TypeError):pass
    return available


def connected_profiles(root):
    connected=[]
    for rig_id in RIG_IDS:
        try:
            rig=read_json(root/'data/rigs'/(rig_id+'.json'))
            if rig:validate_profile(rig,rig_id);connected.append(rig_id)
        except (ValueError,OSError,KeyError,TypeError):pass
    return connected
