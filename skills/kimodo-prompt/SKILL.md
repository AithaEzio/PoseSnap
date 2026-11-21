---
name: kimodo-prompt
description: Turn a simple body-pose idea into a focused English prompt for PoseSnap Text to Pose using Kimodo. Preserve anatomical sides and actor ownership, expand unspecified body language, and clarify conflicting or unsupported requirements.
---

# Kimodo prompt writer for PoseSnap

Use these instructions when the user asks you to turn an idea into a prompt for **PoseSnap Text to Pose**. They are self-contained: no repository, tools, companion files or online service is required. When this file is attached to an LLM conversation, treat it as prompt-writing guidance for the requested task, not authorization to change an app or run inference.

## Deliver a useful prompt immediately

For a clear request such as “a confident pose”, write one polished prompt. Make a small number of coherent creative choices where the user left details open. Ask one concise clarification only when a material requirement is ambiguous, contradictory or unsupported. Do not require a questionnaire for an ordinary mood or action.

The user’s explicit instructions are authoritative. Preserve requested actors, anatomical sides, limb positions, support and deliberate symmetry. Add character through unspecified details; do not change the requested action to make the pose more dramatic.

## Know the target application

This skill targets PoseSnap’s current **creation-only, static body-pose workflow**:

- Kimodo supplies body motion. PoseSnap selects static moments and fits them to the chosen Genesis 8 Female, Genesis 8 Male or Genesis 9 figures. It does not export a motion sequence here.
- One or two characters are available. Two bodies are generated separately, then fitted into a supported arrangement. Use **Person 1** and **Person 2** for ownership.
- **Approximate hand shapes is off by default.** Off means relaxed fingers. On enables PoseSnap’s approximate rule-based gestures and finger controls; these are not Kimodo finger predictions.
- **Pose character** offers Natural, Expressive, Dramatic, Happy, Sad and Tired. These guide unspecified body language. An explicit mood in the direction takes priority. Natural is a safe default for a self-contained prompt.
- Up to three valid choices and **More like this** help explore a direction. Fully constrained requests may yield fewer choices.
- Facial expressions, eye direction, eyelids, tongue and cheek movements are not generated in this mode. Expression studio extracts facial expressions from images and offers facial controls separately.
- This mode has no reference-image input, **Modify current**, exact edit/preservation operation, animation timeline, generated props, identity changes or character-scale changes.
- Seating, kneeling, lying, crawling, inverted support and partner contacts remain experimental. A clear prompt may still fail motion selection or fitting.

Do not advertise NVIDIA’s separate timeline, native constraint tracks, CFG controls or duration options as PoseSnap controls.

## Understand the idea before expanding it

Silently identify:

1. The main stance or action and the static moment that matters.
2. The number of actors and ownership of every requested body movement.
3. Mandatory anatomical sides, limb positions, support, contacts and symmetry.
4. Mood or energy that should be expressed through posture.
5. Details left open for a coherent creative interpretation.
6. Requirements that need a separate Studio step or clarification.

Accept user ideas in their language; produce the copyable pose prompt in clear English for the current application’s checked vocabulary. You may explain settings or ask a question in the user’s language. Do not infer a Genesis generation or change the selected figure from words such as “woman” or “man”.

## Compose the physical body description

Begin a single-person direction with a clear subject, normally **“A person…”**. Use present-tense natural language and focus on one action or at most two compatible behaviors. A few sentences with moderate detail work as a starting point. Stay below **2,000 characters**; leave comfortable room rather than filling the field.

Use this optional order, keeping only the parts that help:

> A person [main action or stance] with [body-language quality]. [Support or weight distribution]. [A few defining limb, torso or head details].

Expand the physical details that make this particular pose recognizable before adding mood adjectives. A concise paraphrase can leave the crucial geometry unspecified. For a constrained pose, three to five focused sentences are often useful; an ordinary stance may need less. Longer is not automatically better.

Useful details include:

- Weight over one supporting leg, both feet grounded, or both feet airborne.
- A contrasting arm position, a hand on the waist, or a clearly raised arm.
- Torso inclination, a natural shoulder offset, or a head turn.
- A visible action phase such as an airborne jump or a walking stride.

Translate emotion into the body: confidence can use a supported weight shift and open posture; fatigue can use low shoulders and a modest torso lean. Do not add smiles, frowns, eyelid changes or eye movements to the copyable prompt.

Use asymmetry when it serves an unspecified detail. Do not force asymmetry onto a request for both arms overhead, a symmetric stance or another intentionally balanced pose. Avoid introducing unrelated gestures or extreme movement just to make the prompt sound creative.

## Expand the defining action through the body

For a hand-led action such as presenting, reaching or holding an implied prop, describe the **arm chain**, not just the object or the hand's destination:

- Where the upper arm points: forward, overhead, down or beside the torso.
- Whether the elbow is extended or bent, and where the hand finishes relative to the shoulder, chest or hip.
- The forearm/wrist alignment when it defines the silhouette. Keep finger shape separate from arm placement.
- The supporting stance and torso orientation needed for that action.

Use only the links needed to resolve the intended silhouette. Do not turn every prompt into a joint inventory. “Holding a pistol toward the camera” does not, by itself, explain whether the hand is at the hip, chest or shoulder. If the user also requests an extended forward arm, make that geometry explicit. If hip-level versus shoulder-level placement would materially change an otherwise ambiguous request, ask or disclose the chosen placement.

Translate “heroic”, “confident” or “powerful” into compatible posture. If both legs must be straight, use grounded support, an upright torso and a deliberate arm contrast; do not add a bent knee, crossed step or pronounced hip shift merely to suggest confidence. Recheck every mandatory detail after expansion.

Use explicit final-state anchor phrases alongside natural description: “the right arm is extended forward”, “the left arm is down”, “both knees are straight” and “the torso stays upright”. These help PoseSnap retain checked goals. Elbow height, wrist orientation and stance width can still depend on model generation and Studio refinement; do not label every descriptive cue as a numeric constraint.

Camera direction requires care. Text to Pose does not read the current orbit camera. “Forward” is relative to the character; a front-facing view is the relevant viewing assumption. Explain this when translating “toward the camera”. A pose aimed at an arbitrary camera angle needs inspection or adjustment in Pose Studio.

Props are implied body-action context. Preserve a requested prop in the natural description when useful, but explain outside the prompt that no prop mesh or fitted object grip is created. Do not replace a required arm direction with an invented prop position. A cupped hand is an approximate optional starting grip, not a prop-specific rig; request the toggle only if such a supported hand shape is explicitly included.

## Choose words that the app can interpret

- Use the character’s own left/right. Do not translate “screen-left” to anatomy unless the facing and intended side are unambiguous. Otherwise ask.
- Repeat sides where needed: “left leg raised, left knee bent, right arm down”. An unsided joint instruction can apply to both sides.
- Clear final states such as “left arm is raised”, “right arm is down”, “torso stays upright” and “head is turned left” are useful. Broader prose may guide Kimodo without becoming an independently checked joint goal.
- Describe head direction as a body movement. Do not promise eye-gaze control.
- Use affirmative final positions. “Do not raise the left arm” alone does not specify where the arm should finish; ask rather than inventing its opposite. If an affirmative target is already supplied, restate it without the exclusion.
- Avoid incidental action words that describe another posture: use “shoulders stay low” rather than “shoulders sit low” for a standing pose.
- Do not include JSON, chat-role labels, Genesis bone IDs, rig-channel numbers, image-prompt weights such as `(pose:1.3)`, negative-prompt blocks, render-quality tags, lens settings or lighting instructions.
- Keep exact angle/contact requests visible in your explanation. Pose Studio is needed to enter or verify precise joint values and contacts; do not promise that prose enforces exact degrees or distances.

## Hands and individual fingers

For a deliberate hand shape, state **Approximate hand shapes: On** outside the prompt and name the side in the prompt.

Supported shapes: relaxed, open, fist, pointing, thumbs-up, peace sign, pinch and cupped. Supported individual fingers: thumb, index, middle, ring and little/pinky. Curl, extend and spread are available; thumb opposition is also supported.

Specify location separately from finger shape. “Right hand forms a peace sign” does not, by itself, put the hand near the head. A whole-hand gesture can be refined by a specific finger instruction, such as “right hand is a fist with the right index finger extended”.

Do not silently enable the option, claim finger prediction, or promise exact skin/fingertip contact. If the user insists the toggle stay off while requesting a deliberate gesture, explain the conflict and ask which requirement to keep.

## Two people and checked contacts

Set **Characters: Two** outside the prompt. Use separate sentences for Person 1 and Person 2. Use “both” only for a shared instruction; avoid unowned “she”, “her” or “his”. A person named as the target of contact is not the owner of the moving hand.

Current contact limits:

- **Handholding:** Person 1’s left hand with Person 2’s right hand, beside the hips, facing the same way. Reversed, overhead and face-to-face arrangements need manual adjustment; do not silently replace them with the supported layout.
- **Front hug:** request the broad hug without assigning specific hugging arms. Adjust exact arm paths and fingers in Pose Studio.
- **Side hug:** identify one acting person and arm, such as Person 2’s right arm around Person 1.
- **Hand on shoulder:** identify the acting person, hand, partner and partner’s shoulder. Do not turn a partner contact into a self-contact.

Do not replace an unsupported contact with a different interaction. Partner lifts, carrying another person, unsupported bindings and precise contacts need manual posing. All supported partner layouts remain experimental.

## Floor support and props

Keep the supporting surfaces coherent. Distinguish a flat foot from toes, a selected knee from both knees, supine/face up from prone/face down, and both feet airborne from a grounded stance.

Crawling uses both palms and knees. Inverted support is a two-hand handstand. One-hand balances and three-point crawling need manual work. Chairs and props are not generated. Mention an implied support only to describe the body and explain that the object must be placed separately in DAZ.

## Clarify without changing the request

Ask a short question when:

- One limb is assigned incompatible final positions, or grounded and airborne support conflict.
- A multi-step sequence is supplied without choosing the static moment.
- A required side or acting person cannot be resolved.
- Only an exclusion is given, without an affirmative pose goal.
- An unsupported contact or exact existing-pose edit is essential.

For a facial-only request, explain that Expression studio handles facial work and ask for a body idea if appropriate. For a mixed body/facial request, you may supply the clear body prompt and separately identify the facial step; never silently drop the requested facial effect or put it into the body prompt.

For “like this image” without a body description, explain that Text to Pose does not accept images and direct image matching to Extract pose. Do not claim Kimodo saw the image. If the user supplies a complete textual body description, work from that description without promising image matching.

For “modify my current pose”, explain that precise edits belong in Pose Studio. A complete newly described pose can be generated, but a fresh generation cannot preserve unrelated joints exactly.

## Output

By default return:

1. **Prompt** — one fenced plain-text block containing only the ready-to-paste English body direction.
2. **Required settings** — only non-default requirements, such as Two characters or Approximate hand shapes On. Keep figure selections unchanged unless the user specifies them.
3. **Assumptions or limits** — a brief note for substantive creative additions, unresolved precision or experimental support/contact. Do not claim the prompt or resulting pose was tested unless it was.

Return alternatives only when requested. An essential unresolved conflict gets a clarification question instead of a purported final prompt.

Before answering, check that the prompt preserves the user’s action, actors, sides and symmetry; that added details fit the support; and that all app settings/explanations are outside the copyable block.

## Worked examples

### Simple mood

User: “A confident pose.”

Prompt:
```text
A person stands confidently with weight on the left leg. The right hand rests on the waist, the left arm is down, and the head is turned right.
```
Assumption: the weight shift, waist placement and head turn are creative choices; the user did not specify those sides.

### Asymmetry with a required arm position

User: “A playful dance, with her left arm down.”

Prompt:
```text
A person dances playfully with weight on the left foot. The left arm is down, the right arm is raised overhead, the right knee is bent, and the head is turned right.
```
Assumption: the raised right arm and head turn fill unspecified details. The required left arm stays down.

### A selected jump moment

User: “Jumping with both feet in the air and both hands up.”

Prompt:
```text
A person jumps upward with both feet in the air. Both arms are raised overhead, both knees are bent, and the torso stays upright.
```
Assumption: bent knees are an added choice for the airborne moment. Keep both requested arms raised; do not introduce asymmetry here.

### Fingers and body location

User: “A relaxed greeting with a peace sign in the right hand.”

Prompt:
```text
A person is standing casually. The right hand forms a peace sign near the shoulder, the left arm is down, and the head is turned right.
```
Required setting: Approximate hand shapes On. Assumption: the shoulder-height location is an added choice. Inspect the estimated fingers.

### Actor and target ownership

User: “Person 2 puts their right hand on Person 1’s left shoulder.”

Prompt:
```text
Person 1 stands relaxed. Person 2 places the right hand on Person 1 left shoulder.
```
Required setting: Characters Two. The relaxed stance is an added choice. Partner contact is experimental; inspect the palm and spacing.

### A prop-led pose with mandatory straight legs

User: “A person holding a pistol in the right hand toward the camera/front, left hand down, confident or heroic, legs straight.”

Prompt:
```text
A person stands in a firm, confident heroic stance, facing forward. Both feet are flat on the floor, spaced about shoulder-width apart, with weight balanced between them and both knees straight. The right arm is extended forward at shoulder height, with the right elbow straight and the forearm and wrist aligned, holding a pistol toward the front. The left arm is down beside the torso, with the left hand resting by the left thigh. The torso stays upright and the head faces forward.
```
Assumption: shoulder-height reach, shoulder-width spacing and balanced weight fill unspecified details. Forward means the character's front, viewed from a front-facing camera. No pistol mesh is generated. Exact aim, stance width and object grip need inspection in Pose Studio/DAZ; the prompt does not claim a verified fit. Approximate hand shapes can stay Off because this prompt does not request a supported finger shape.

### Clarification

User: “Her left arm is up and down.”

Ask: “Should her left arm finish raised or lowered?”

User: “First walk to a chair, then sit and stand.”

Ask: “Which static moment do you want: walking, seated, or standing?”

User: “Two people hold hands overhead, facing each other.”

Explain: that layout needs manual adjustment in Pose Studio. Ask whether to write a starting body-pose prompt for that manual arrangement; do not silently substitute low, same-facing handholding.

## Basis and limits

Reviewed 25 October 2026 against PoseSnap’s creation-only Kimodo workflow. These are prompt-writing recommendations, not a guarantee of motion quality, exact fitting or compatibility with every LLM. References are optional further reading; the skill works offline.

- [NVIDIA Kimodo best practices](https://research.nvidia.com/labs/sil/projects/kimodo/docs/key_concepts/limitations.html)
- [Kimodo-SOMA-RP-v1.2 model card](https://huggingface.co/nvidia/Kimodo-SOMA-RP-v1.2)
- [BONES-SEED natural-language descriptions](https://huggingface.co/datasets/bones-studio/seed#natural-language-descriptions)
