"""Instance identity and selection contracts; no model imports at startup."""
import hashlib, json, math
from storage import read_json

DETECTION_VERSION = 4
MASK_VERSION = 2
SOURCE_VERSION = 3

def identity(person):
    value = {k: person.get(k) for k in ('box', 'keypoints', 'detector', 'detectionVersion', 'contextKey')}
    value['maskVersion'] = MASK_VERSION
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()[:24]

def cached_source(folder, person, choice='smart',context=None,raw=False):
    if isinstance(context,dict) and context.get('version')==1 and context.get('id')=='original':raw=True
    if not raw:
        from reference_guidance import saved_source
        guided=saved_source(folder,person,choice,context)
        if guided is not None or context is not None:return guided
    from extraction import cache_matches
    paths=(source_path(folder,person,choice),) if choice=='pure' else (source_path(folder,person), folder/f"solve-{person['id']}.json")
    for path in paths:
        try:source=read_json(path)
        except (OSError,ValueError):continue
        if source and source.get('version') in (2,SOURCE_VERSION) and source.get('personKey')==identity(person) and cache_matches(source,choice):return source
    return None

def source_path(folder, person, choice='smart'):
    from extraction import method, PURE_VERSION
    suffix=f'-pure-v{PURE_VERSION}' if method(choice)=='pure' else ''
    return folder/f"solve-{person['id']}-{identity(person)}{suffix}.json"

def visible_points(person, threshold=.55):
    return {i: p[:2] for i, p in enumerate(person.get('keypoints', [])) if len(p) == 3 and p[2] >= threshold}

def anchor(person):
    # Ears are safer than a nose at the contact point of two touching faces.
    points = person.get('keypoints', [])
    head = [points[i] for i in (3, 4) if len(points) > i and points[i][2] >= .5]
    if not head: head = [points[i] for i in range(min(5, len(points))) if points[i][2] >= .55]
    if head:
        best = max(head, key=lambda p: p[2])
        return best[:2]
    a, b, c, d = person['box']
    return [(a+c)/2, b+(d-b)*.18]

def nested_body_boxes(a,b):
    boxes=[p['box'] for p in (a,b)]
    widths=[box[2]-box[0] for box in boxes];heights=[box[3]-box[1] for box in boxes]
    if min(widths)<=0 or min(heights)<=0 or max(widths)/min(widths)>1.3:return False
    intersection=max(0,min(boxes[0][2],boxes[1][2])-max(boxes[0][0],boxes[1][0]))*max(0,min(boxes[0][3],boxes[1][3])-max(boxes[0][1],boxes[1][1]))
    return intersection/min(w*h for w,h in zip(widths,heights))>=.95

def duplicate(a, b):
    """Boxes can coincide; a duplicate must also agree on visible anatomy."""
    pa, pb = visible_points(a), visible_points(b)
    common = set(pa) & set(pb)
    if len(common) < 5: return False
    heights=[p['box'][3]-p['box'][1] for p in (a,b)]
    scale=max(24,max(heights) if nested_body_boxes(a,b) else min(heights))
    close = sum(math.dist(pa[i], pb[i]) < scale*.035 for i in common)
    return close / len(common) >= .8

def distinct_people(candidates):
    kept = []
    for person in sorted(candidates, key=lambda p: p['score'], reverse=True):
        repeated=next((i for i,old in enumerate(kept) if duplicate(person,old)),None)
        if repeated is None:kept.append(person)
        else:
            old=kept[repeated]
            own_points=visible_points(person);old_points=visible_points(old)
            more_leg_evidence=sum(i in own_points for i in (13,14,15,16))>=sum(i in old_points for i in (13,14,15,16))+2
            if nested_body_boxes(person,old) and len(own_points)>=len(old_points) and more_leg_evidence:
                kept[repeated]=person
    return sorted(kept, key=lambda p: tuple(anchor(p)))

def mask_prompts(person, others):
    """Prompt reliable core anatomy; discard anchors at an ambiguous crossing."""
    own = visible_points(person, .7)
    # Limbs crossing at wrists/elbows are poor instance-identity prompts.
    core = [anchor(person)] + [own[i] for i in (11,12,13,14,15,16) if i in own]
    negative = [anchor(p) for p in others]
    for other in others:
        points = visible_points(other, .85)
        negative.extend(points[i] for i in (11,12,13,14,15,16) if i in points)
    scale = max(24, person['box'][3]-person['box'][1])
    positive = [p for p in core if all(math.dist(p,q) > scale*.025 for q in negative)]
    negative = [p for p in negative if all(math.dist(p,q) > scale*.025 for q in core)]
    if not positive: raise ValueError('This person has no unambiguous visible anchor. Try a clearer reference.')
    return positive, negative

def mask_quality(mask, positive, negative):
    def contains(point):
        x, y = map(lambda v: int(round(v)), point)
        return 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and bool(mask[y,x])
    positive_hits = sum(contains(p) for p in positive) / len(positive)
    negative_hits = sum(contains(p) for p in negative) / max(1,len(negative))
    return positive_hits >= .8 and negative_hits == 0
