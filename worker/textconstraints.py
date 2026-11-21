"""Independently enforce explicit body movements and ownership.

These are semantic checks, never extra image evidence. Unrecognized wording remains
Kimodo's input; unsupported directions clarify before application.
"""
import re
from instructions import clauses, negated, positive_text


def posture_recipe(text):
    text = positive_text(text)
    for pattern,recipe in ((r'jump\w*','jump'),(r'(?:seated|sitting|sits?|sat)','seated'),(r'crouch\w*','crouch'),(r'kneel\w*','kneel'),(r'(?:lying|lies?(?: down)?|prone|supine)','lying'),(r'walk\w*','walking'),(r'run\w*','running'),(r'danc\w*','dance'),(r'confident','confident'),(r'relaxed','relaxed'),(r'defensive','defensive'),(r'sad','sad'),(r'happy','happy'),(r'(?:standing|stands?|neutral)','standing')):
        if re.search(r'\b'+pattern+r'\b',text,re.I):return recipe
    return None


def interaction_request(text):
    """Recognize supported partner contacts independently of prose parsing."""
    matches=set()
    for clause in body_clauses(text.replace('-', ' ')):
        if negated(clause):continue
        if re.search(r'\bside hugs?\b|\bhugging (?:from )?(?:the )?side\b',clause):matches.add('side_hug')
        elif re.search(r'\bhugs?\b|\bhugging\b',clause):matches.add('front_hug')
        if re.search(r'\b(?:hold(?:ing)? hands|handholding)\b',clause):matches.add('handhold')
        if re.search(r"\bhand\s+on\s+(?:(?:the|their|partner(?:'s)?|(?:person|actor) [12](?:['’]s)?)\s+)?(?:own\s+)?(?:left |right )?shoulder\b",clause):matches.add('shoulder')
    if len(matches)>1:raise ValueError('Choose one partner contact for this preview.')
    return next(iter(matches),'none')


def contact_owners(text):
    return list(re.finditer(r"\b(?:person|actor) ([12])(?:['’]s)?\s+(?:(?:puts?|rests?|places?)\s+)?(?:(?:the|a|their)\s+)?(?:(left|right)\s+)?(?:hand|arm|hugs?|side hug)\b",text,re.I))


def actor_text(prompt, actor, count):
    if count==1:return prompt
    # A partner named as an object is not a new instruction subject.
    mentions=re.finditer(r'\b(?:actor|person) ([12])\b(?!\s*[\'’]s\b)',prompt,re.I)
    objects=r'\b(?:at|toward|towards|to|on|with|of|for|behind|beside|near|against|around|faces?|facing|hugs?|hugging|touch(?:es|ing)?|holds?|holding|supports?|supporting)\s+$'
    def subject(mention):
        prefix=prompt[:mention.start()];suffix=prompt[mention.end():]
        if re.search(r'(?:^|[.;])\s*(?:for|to)\s+$',prefix,re.I):return True
        if re.search(r'\bwith\s+$',prefix,re.I) and re.match(r'\s+(?:is|has|keeps?|smil(?:es|ing)|frown(?:s|ing))\b',suffix,re.I):return True
        return not re.search(objects,prefix,re.I)
    clauses=[m for m in mentions if subject(m)]
    if clauses:return ' '.join(prompt[m.end():clauses[i+1].start() if i+1<len(clauses) else len(prompt)] for i,m in enumerate(clauses) if int(m[1])==actor)
    return prompt if re.search(r'\b(both|hug|holding hands|hold hands|each other)\b',prompt) else ''


def positional_part(part, movement):
    # Hand location is an arm-chain goal; hand gestures still drive the fingers.
    return part[:2]+'arm' if part.endswith('_hand') and movement in ('raise','lower','forward','back') else part


def limbs(text):
    """Checked directional phrases define explicit body goals."""
    return [change for clause in body_clauses(text) for change in limb_clause(clause)]


def body_clauses(text):
    return list(clauses(text))


def limb_clause(text):
    text=text.lower()
    if negated(text) or re.search(r"\b(slightly|partway|halfway|half|quarter|degrees?)\b|\ba little\b|\d+\.\d+|\d+\s*%",text):return []
    result=[]
    pattern=r'\b(raises?|raised|lowers?|lowered|straightens?|bends?|bent)\s+(?:(?:the|her|his|their)\s+)?(?:(left|right|both)\s+)?(arm|hand|leg|knee|foot|feet)s?\b|\b(?:(left|right|both)\s+)?(arm|hand|leg|knee|foot|feet)s?\s+(?:(?:are|is|stays?|remains?|stretches?)\s+)?(up|down|low|overhead|raised|lowered|bent|straight)\b'
    for c in re.finditer(pattern,text):
        movement,side,part=c.group(1,2,3) if c[1] else (c[6],c[4],c[5])
        movement={'up':'raise','overhead':'raise','raised':'raise','raises':'raise','down':'lower','low':'lower','lowered':'lower','lowers':'lower','bent':'bend','bends':'bend','straight':'straighten','straightens':'straighten'}.get(movement,movement)
        if part in ('arm','hand') and movement=='straighten' and re.match(r'\s+(?:forward|backward|back)\b',text[c.end():]):continue
        # "Legs in air" is support, not a command to raise both thighs.
        for side in (['l'] if side=='left' else ['r'] if side=='right' else ['l','r']):
            result.append(dict(part=side+'_'+({'hand':'arm','feet':'foot'}.get(part,part)),movement=movement,amount=1.))
    reach=r'(?:stretch(?:es|ed|ing)?|reach(?:es|ed|ing)?|extend(?:s|ed|ing)?)'
    direction=r'(forward|backward|back|behind (?:the |her |his |their )?torso)\b'
    for pattern in (
        r'\b(left|right|both) (arm|hand)s?\s+(?:(?:is|are|stays?|remains?)\s+)?(?:'+reach+r'\s+)?(?:straight\s+)?'+direction,
        r'\b'+reach+r'\s+(?:(?:the|her|his|their)\s+)?(left|right|both) (arm|hand)s?\s+(?:straight\s+)?'+direction,
    ):
        for c in re.finditer(pattern,text):
            movement='forward' if c[3]=='forward' else 'back'
            for side in (('l','r') if c[1]=='both' else ('l',) if c[1]=='left' else ('r',)):
                result.append(dict(part=side+'_arm',movement=movement,amount=1.))
    for c in re.finditer(r'\b(left|right|both) (?:arm|hand)s?\s+(?:(?:is|are)\s+)?(?:hang(?:s|ing)?|rest(?:s|ing)?)\s+(?:(?:relaxed|naturally|loosely|comfortably)\s+)?(?:down\s+)?(?:at|by)\s+(?:the |her |his |their )?sides?\b',text):
        for side in (('l','r') if c[1]=='both' else ('l',) if c[1]=='left' else ('r',)):
            result.append(dict(part=side+'_arm',movement='lower',amount=1.))
    return result


def waist_arms(text):
    return {side:'waist' for clause in body_clauses(text) if not negated(clause)
            for match in re.finditer(r'\b(left|right|both) hand(?:s)? (?:rests? |stays? |is |are )?on (?:the |her |his |their )?waist\b',clause)
            for side in (('l','r') if match[1]=='both' else ('l',) if match[1]=='left' else ('r',))}


def enforce(intent, payload):
    if intent['status'] != 'plan': return intent
    if payload['output']!='expression':
        contact=interaction_request(payload['prompt'])
        if contact!='none':
            if len(payload['actors'])!=2:return dict(status='clarify',message='Choose two actors for this interaction.')
            intent['interaction']=contact
    if payload.get('creative') and payload.get('mode')=='create' and payload['output']!='expression':
        from textpose import basic_intent
        reviewed=basic_intent(payload)
        if reviewed['status']=='plan':
            for row,known in zip(intent['actors'],reviewed['actors']):
                if row.get('recipe')!='kimodo' and (known['recipe']!='standing' or re.search(r'\b(?:standing|stand|neutral)\b',payload['prompt'],re.I)):row['recipe']=known['recipe']
                requested={positional_part(c['part'],c['movement']) for c in known['changes']}
                row['changes']=[c for c in row['changes'] if positional_part(c['part'],c['movement']) not in requested]+known['changes']
                row['preserve']=list(dict.fromkeys([*row['preserve'],*known['preserve']]))
                row['support'].update(known['support'])
            if reviewed.get('interaction','none')!='none':intent['interaction']=reviewed['interaction']
    prompt = payload['prompt'].lower()
    for actor in intent['actors']:
        text = actor_text(payload['prompt'].lower(),actor['id'],len(intent['actors']))
        if not text:continue
        if payload.get('mode')=='create' and payload['output']!='expression':
            # Physical action stays authoritative even when a full reviewed
            # phrase parser cannot interpret the surrounding mood or edits.
            posture=posture_recipe(text)
            if actor.get('recipe')!='kimodo' and posture in ('standing','seated','crouch','kneel','lying','walking','running','dance','jump'):
                actor['recipe']=posture
        if re.search(r'\b(?:keep|preserve)\b.{0,25}\bfinger shapes?\b',text):
            actor['preserve']=list(dict.fromkeys([*actor.get('preserve',[]),'fingerShapes']))
        from hand_design import phrases as hand_phrases
        explicit=[*limbs(text), *hand_phrases(text)] if payload['output']!='expression' else []
        waist=waist_arms(text) if payload.get('mode')=='create' and payload['output']!='expression' else {}
        if payload['output']!='expression':
            weights={m[1][0] for clause in body_clauses(text) if not negated(clause)
                     for m in re.finditer(r'\bweight\s+(?:is\s+)?(?:on|over)\s+(?:the |her |his |their )?(left|right)\s+(?:leg|foot)\b',clause)}
            if len(weights)>1:return dict(status='clarify',message='Choose one supporting leg for this weight shift. Your accepted result is kept.')
            if weights:actor['design']={**actor.get('design',{}),'weight':next(iter(weights))}
        if waist:
            if any(c['part'][:1] in waist and positional_part(c['part'],c['movement']).endswith('_arm') for c in explicit):
                return dict(status='clarify',message='Choose one final arm position: a hand on the waist or a directional arm movement. Your accepted result is kept.')
            actor['design']={**actor.get('design',{}),'arms':{**actor.get('design',{}).get('arms',{}),**waist}}
            actor['changes']=[c for c in actor['changes'] if c['part'][:1] not in waist or not positional_part(c['part'],c['movement']).endswith('_arm')]
        goals={}
        for change in explicit:
            part=change['part']
            if part in goals and goals[part]['movement']!=change['movement']:
                return dict(status='clarify',message='Choose one final direction for '+part.replace('l_','left ').replace('r_','right ')+'. Your accepted result is kept.')
            goals[part]=change
        if goals:
            actor['changes']=[c for c in actor['changes'] if positional_part(c['part'],c['movement']) not in goals]+list(goals.values())
        requested_motion=re.search(r'\b(raise|lower|bend|straighten|lean|turn)\b|\b(?:arms?|hands?|legs?|knees?|feet|foot)\s+(?:(?:is|are)\s+)?(?:up|down|overhead|raised|lowered|bent|straight)\b',text)
        if payload['output']!='expression' and requested_motion and not actor['changes'] and intent.get('interaction','none')=='none':
            return dict(status='clarify',message='The interpreter did not produce the requested body change. Name the actor’s left or right body part and one final movement, such as “lower the left arm”. Your accepted result is kept.')
        if payload.get('mode')=='create':
            # Deliberate finger gestures need actor-owned instructions. A
            # second actor's peace sign must not become this actor's default.
            deliberate={'fist','point','thumb_up','peace','pinch','cupped'}
            owned={(c['part'],c['movement']) for c in explicit}
            actor['changes']=[c for c in actor['changes'] if c['movement'] not in deliberate or (c['part'],c['movement']) in owned]
        if payload['output'] != 'expression' and re.search(r'\b(standing|stands?|seated|sitting)\b', positive_text(text)) and not re.search(r'\b(air|airborne|jump|jumping|float|floating|leap|suspend|lifted)\b', positive_text(text)):
            actor['support'] = {'l': 'flat', 'r': 'flat', **actor['support']}
    return intent


def preflight(payload):
    text=payload['prompt'].lower()
    if re.search(r'\b(?:reference|ref image|input image|this image|this photo)\b',positive_text(text)):
        return dict(status='clarify',message='Text to Pose accepts body directions, not image references. Extract the image in Extract pose, then refine its joints in Pose Studio.')
    if payload['output']!='expression':
        from hand_design import phrases
        for actor in payload['actors']:
            clause=actor_text(payload['prompt'].lower(),actor['id'],len(payload['actors']));goals={}
            for change in (*limbs(clause),*phrases(clause)):
                part=positional_part(change['part'],change['movement'])
                if part in goals and goals[part]!=change['movement']:
                    return dict(status='clarify',message='Choose one final movement for '+part.replace('l_','left ').replace('r_','right ')+'. Your accepted result is kept.')
                goals[part]=change['movement']
    if negated(text) and not positive_text(text) :
        return dict(status='clarify',message='Describe the final movement you want. An exclusion alone does not select a new pose; your accepted result is kept.')
    for clause in clauses(text):
        if negated(clause) and re.search(r'\b(?:turn|lean|raise|lower|bend|straighten|jump|kneel|sit|stand|hug|clench|curl|extend|smile|frown|wink|squint|open|close)\w*\b', clause):
            return dict(status='clarify',message='Describe the final movement you want. An excluded direction does not specify its opposite; your accepted result is kept.')
    try:contact=interaction_request(text) if payload['output']!='expression' else 'none'
    except ValueError as error:return dict(status='clarify',message=str(error)+' Your accepted pose is kept.')
    if payload['output']!='expression' and re.search(r'\b(?:one|single)[ -]hand(?:ed)?\b.{0,20}\bhandstand\b|\bhandstand\b.{0,25}\b(?:one|single) hand\b|\bthree[ -]point\b.{0,20}\bcrawl|\bcrawl\w*\b.{0,25}\bone hand\b',text):
        return dict(status='clarify',message='The current floor fitter supports two-hand handstands and crawling on both palms and knees. Use Pose Studio for a one-hand balance or a three-point crawl; your accepted pose is kept.')
    if contact=='handhold':
        ownership=list(re.finditer(r"\b(?:person|actor) ([12])(?:['’]s)?\s+(?:(?:uses?|holds?|holding)\s+)?(?:with\s+)?(?:(?:the|a|their)\s+)?(left|right) hand\b",text))
        reversed_hand=any(m[2]!=('left' if m[1]=='1' else 'right') for m in ownership)
        unclear_side=any(not any(owner.start()<=hand.start()<owner.end() for owner in ownership) for hand in re.finditer(r'\b(?:left|right) hands?\b',text))
        special_layout=bool(re.search(r'\b(?:raised|overhead|above|diagonal(?:ly)?)\b|\b(?:face|faces|facing) (?:each other|one another)\b|\bface[ -]to[ -]face\b|\b(?:raise|lift)\b.{0,25}\bhands?\b|\bhands? up\b',text))
        if reversed_hand or unclear_side or special_layout:
            return dict(status='clarify',message='Handholding currently supports Person 1’s left hand with Person 2’s right hand beside the hips, facing the same way. Other layouts need adjustment in Pose Studio; your accepted pose is kept.')
    if contact in ('side_hug','front_hug','shoulder'):
        owners=contact_owners(text)
        hands=list(re.finditer(r'\b(?:left|right) (?:hand|arm)\b',text))
        unbound=any(not any(owner.start()<=hand.start()<owner.end() for owner in owners) for hand in hands)
        target=re.search(r"\bon\s+(?:the\s+)?(?:person|actor) ([12])(?:['’]s)?\s+(?:left |right )?shoulder\b",text)
        self_target=contact=='shoulder' and (bool(target) and target[1]==(owners[0][1] if owners else '1') or bool(re.search(r'\bon (?:their |his |her )?own (?:left |right )?shoulder\b',text)))
        if unbound or (contact=='front_hug' and hands) or (contact!='front_hug' and len(owners)>1) or self_target:
            return dict(status='clarify',message='For a specific partner contact, name one actor and arm first, such as “Person 2 right hand on Person 1 left shoulder” or “Person 2 right arm side hug”. Use Pose Studio for other arrangements; your accepted pose is kept.')
    if re.search(r'\b(image.left|image.right|screen.left|screen.right)\b',text):return dict(status='clarify',message='Use the actor’s anatomical left or right for this direction. Image-left depends on their facing and reference camera.')
    if re.search(r'\b(extra arms|animation|five people|four people|three people|unseen side|skin texture|invisible|teleport|lift the partner|carries|carrying|piggyback)\b|\bcarry (?:person|actor|the partner)',text):return dict(status='unsupported',message='This version supports static body poses for one or two actors. Extra limbs, animation, lifts, new textures and unseen-view reconstruction are outside its supported actions.')
    if re.search(r'\b(identity|younger|older|taller|shorter|scale|breast size|nose smaller|nose bigger)\b',text):return dict(status='unsupported',message='Text to Pose changes body posture. Character shape and scale stay untouched.')
    if re.search(r'\b(raise and lower|open and close|left and right at the same time)\b',text):return dict(status='clarify',message='Choose one final state for that body joint.')
    if len(payload['actors'])==2 and re.search(r'\b(she|he|her|his)\b',text) and not re.search(r'\b(both|person [12]|actor [12])\b',text):return dict(status='clarify',message='Which actor should change? Name Person 1, Person 2, or both.')
    return None
