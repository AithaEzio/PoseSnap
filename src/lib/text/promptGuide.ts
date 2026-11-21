import type {HelpTopic,PromptExample} from '../help';
import examples from './prompt-examples.json';
import {profiles} from './types';

const topic=(id:string,title:string,text:string,extra:Partial<HelpTopic>={}):HelpTopic=>({id:'kimodo-'+id,section:'kimodo',title,tag:'Kimodo prompt guide · Text to Pose',text,...extra});
const exampleGroups=['Mood and stance','Actions','Floor and support','Hands and fingers','Partner contacts'];
export const promptGuideTopics:HelpTopic[]=[
  topic('start','Start here: a thought to a body pose','Describe the body pose you want to create. Kimodo supplies a short motion; PoseSnap chooses static moments, fits them to your selected Genesis figures and presents the valid choices.',{
    steps:[
      'Choose One or Two characters and the Genesis generation for each person. Keep your existing figure selection unless you intend to change it.',
      'Write one self-contained body direction. Start with the main stance or action, then add the few details that matter most.',
      'Choose Preview result. Inspect the body from Front, Side and Back, switch between the available choices, and read Understood changes and Text notes.',
      'Apply to keep a result, or Cancel preview to keep the previously accepted result. Edit in Pose Studio for precise joints and contacts, then send to DAZ or save a DUF.'
    ],
    paragraphs:[
      'More like this requests fresh choices for the same direction and options. It is available after a matching preview or accepted creation. After changing the text, characters, profile or hand option, Preview result first. A tightly constrained request may yield fewer than three distinct valid choices.',
      'Text to Pose creates body poses. Facial expression extraction and adjustment belong in Expression studio. This mode has no image-reference input, Modify current, motion timeline or animation export. Changing the direction creates a new proposal; it does not make a precise edit to the accepted pose.'
    ]
  }),
  topic('build','Build a clear prompt','Use this order as a checklist, not a form to fill in completely: a person → main action or stance → mood in the body → support or weight → a few defining limb, torso or head details.',{
    paragraphs:[
      'Begin a single-person prompt with a clear subject, usually “A person…”. Use ordinary English and one or two compatible behaviors. A few focused sentences are a useful starting point; the field limit is 2,000 characters, not a target to fill.',
      'For a still pose, describe the moment you want: the airborne phase of a jump, a walking stride, or a resting stance. PoseSnap selects a moment from generated motion. It cannot show a whole sequence such as walking, sitting and then jumping as one pose.',
      'Tell the model what the body does. Put character generation, hand options and other app settings in the controls. Clothing, lighting, lens settings, “8K”, render styles, JSON, Genesis bone IDs and image-prompt weights do not define a better body pose here.'
    ],
    bullets:[
      'Action: stands casually, walks forward, celebrates, dances or kneels.',
      'Support: weight on the right leg, both feet in the air, left foot flat, or both palms on the floor.',
      'Defining details: left arm raised, right hand on the waist, torso upright, head turned left.',
      'Leave minor details free when they do not matter. Naming every joint can overconstrain or blur the intended action.'
    ],
    examples:[{id:'template',group:'Template',title:'A compact prompt template',prompt:'A person [main action or stance] with [body-language quality]. [Support or weight cue]. [Two or three important body details with clear anatomical sides].',actors:1,handShapes:false,notes:'Replace the bracketed descriptions before using this template. Keep only the parts needed for your idea.'}]
  }),
  topic('priorities','Choose detail and resolve conflicts','Decide which features make the pose recognizable. Keep these explicit and let smaller details vary. Clear wording helps interpretation; it does not guarantee that every generated body can satisfy the request.',{
    bullets:[
      'Describe a final state: “the left arm is down” is clearer than “do not raise the left arm”. An exclusion alone does not specify the arm’s final position.',
      'Resolve contradictions before generating. The same foot cannot be planted and airborne; the same arm cannot finish both raised and lowered.',
      'Keep each request self-contained. “Make it more like before” has no reliable pose description, and this mode does not modify the current accepted body.',
      'Use recognizable physical cues. “Shoulders stay low” describes a standing mood more clearly than “shoulders sit low”, which can be interpreted as seating.',
      'Expand the defining action through its arm chain: upper-arm direction, elbow bend or extension, hand height and a coherent stance. Holding an implied object does not, by itself, specify those body positions. Add the few details that matter rather than a longer list of adjectives.',
      'Forward is character-relative. Text to Pose does not read your orbit camera. Check a camera-facing reach in Front view; precise aim at another camera angle needs Pose Studio.',
      'Exact degrees, finger intersections and precise prop contact require inspection and adjustment in Pose Studio. Do not treat a fluent summary as proof that the fitted joints matched.'
    ]
  }),
  topic('expression','Give body language character','Show mood through the body: a supported weight shift, shoulder height, torso inclination, head direction and contrasting limb positions. Body language can suggest confidence or sadness while facial controls stay unchanged.',{
    paragraphs:[
      'For variety, specify a meaningful asymmetry such as weight on one leg and different arm positions. Add only cues that fit the action and balance. Symmetry is useful for a two-arm celebration, prayer or a deliberately balanced stance; keep it when it is part of your request.',
      'Pose character offers '+profiles.map(p=>p[0].toUpperCase()+p.slice(1)).join(', ')+'. Natural adds no mood preset. The other profiles guide unspecified body language. A mood stated explicitly in the direction takes priority, so use a compatible profile or leave Natural selected.',
      'If the result feels generic, add one defining physical cue before adding more adjectives. Compare alternatives and use More like this for another batch. Profiles and longer wording cannot guarantee better results.'
    ]
  }),
  topic('sides','Left, right and head direction','Left and right mean the character’s own anatomy. In a front view, their left appears on your right. A camera view does not rename their limbs.',{
    bullets:[
      'Repeat the side when several joints matter: “left leg raised, left knee bent, right arm down”. A bare “knee bent” can be read as applying to both knees.',
      'Use clear final-state wording such as “the left arm is raised” or “the right arm is down”. Broader prose can guide Kimodo without becoming an independently checked joint goal.',
      'Use “head turned left” to describe a body joint. Eye direction, eyelid closure and facial emotion are separate expression controls.',
      'Avoid “screen left” and “the hand on the left of the picture”. Resolve the character’s side first. Text to Pose does not inspect a reference image.',
      'For two people, name Person 1 and Person 2 before their body directions. A partner named after “on” or “around” is the target, not a new owner of the moving arm.'
    ]
  }),
  topic('hands','Hands, gestures and individual fingers','Approximate hand shapes is off by default. Generated bodies use relaxed fingers. Turn it on when you explicitly request a supported gesture or individual finger movement.',{
    paragraphs:[
      'Available hand shapes are relaxed, open, fist, pointing, thumbs-up, peace sign, pinch and cupped. Name the left hand, right hand or both hands. For example, “right hand forms a peace sign” is a finger request; “right arm raised” is a body request.',
      'Individual thumb, index, middle, ring and little/pinky fingers can be curled, extended or spread. Thumb opposition is also supported. Name the side and the finger. A specific finger instruction can refine a requested whole-hand shape, such as a fist with the right index finger extended.',
      'These are PoseSnap’s rule-based estimates, not finger predictions from Kimodo. Hand and wrist location comes from the body pose and fitting; a peace sign does not, by itself, specify where to hold the hand. Inspect fingers, palms and any contact in Pose Studio. Rig limits can make a requested shape unavailable.'
    ]
  }),
  topic('partners','Two characters and partner contacts','Choose Two, then match Person 1 and Person 2 to their intended figures. Write each person’s body direction explicitly, or use “both” for a shared action. Kimodo generates each body separately; PoseSnap then fits the supported arrangement.',{
    bullets:[
      'Handholding: Person 1’s left hand with Person 2’s right hand, beside the hips and facing the same way. Raised, reversed and face-to-face handholding need manual adjustment.',
      'Front hug: request the broad interaction. Specific named hugging arms are outside the currently checked layout; arrange them in Pose Studio.',
      'Side hug: name one acting person and arm, such as Person 2’s right arm around Person 1.',
      'Hand on shoulder: name the acting person, hand, target person and target shoulder. The partner’s shoulder is different from the actor’s own shoulder.',
      'All partner contacts remain experimental. Mixed generations and proportions can require spacing and palm adjustments. Partner lifts, carrying a person and unsupported bindings are not supported.'
    ],
    paragraphs:['Approximate hand shapes may add an estimated contact grip when enabled. With it off, fingers stay relaxed even when body placement makes the palms meet. Neither option proves convincing skin or fingertip contact.']
  }),
  topic('floor','Floor support and implied props','Name the support that makes the pose possible: a flat foot, selected knee, back or front of the body, or both palms. Inspect the result from the side as well as the front.',{
    bullets:[
      'Jumping: ask for both feet in the air when the airborne moment matters; do not also request grounded feet.',
      'Seated: describe the seated posture and feet. A chair is an implied support; no chair mesh is generated.',
      'Kneeling: distinguish “on the right knee with the left foot flat” from kneeling on both knees.',
      'Lying: “supine” means face up; “prone” means face down. Check the torso and limbs against the floor.',
      'Crawling and handstands: the checked fitter supports both palms and knees for crawling and two-hand inverted support. One-hand balances and three-point crawls need manual work.',
      'Seating, kneeling, lying, crawling and inverted support remain experimental. A physically plausible description can still fail source-frame selection or target fitting.',
      'Props, furniture and environment meshes are not created. Add them in DAZ and adjust contact manually. Do not request character height, identity or scale changes in the pose prompt.'
    ]
  }),
  ...exampleGroups.map((group,index)=>topic('examples-'+index,'Examples · '+group,'Original starting points for your own body directions. Copy the prompt only; required controls and limitations are listed separately.',{examples:examples.filter(e=>e.group===group) as PromptExample[]})),
  topic('rewrites','Six useful prompt rewrites','Improve clarity while keeping the user’s requirements. When a request is contradictory, sequential or ambiguous about a side, clarify it before choosing a replacement.',{
    rewrites:[
      {id:'vague',title:'Vague → a readable body stance',before:'A confident pose.',after:examples.find(e=>e.id==='confident')!.prompt,note:'The action stays confident. The weight shift, hand position and head turn are example creative choices, not facts supplied by the original request.'},
      {id:'overloaded',title:'Overloaded → one chosen moment',before:'A person runs, dances, kneels, jumps and waves, with every arm and leg doing something different.',after:examples.find(e=>e.id==='jump')!.prompt,note:'First ask which moment matters. This replacement assumes the user chose the airborne jump; do not silently drop the other requested actions.'},
      {id:'contradiction',title:'Contradictory → a confirmed final state',before:'The left arm is up and the left arm is down.',after:'A person is standing with the left arm down, the right hand on the waist and the torso upright.',note:'Ask whether the left arm should finish up or down. This example uses down only after the user chooses it.'},
      {id:'screen',title:'Screen-relative → anatomical ownership',before:'Raise the hand on screen left.',after:'A person is standing with the left arm raised and the right arm down.',note:'Ask which anatomical side is intended. This replacement assumes the user confirms the character’s left; it is not an automatic conversion from screen-left.'},
      {id:'sequence',title:'Sequential → a selected static phase',before:'A person walks to a chair, sits down and then stands up.',after:examples.find(e=>e.id==='seated')!.prompt,note:'Ask which pose to keep. This replacement assumes the seated moment. PoseSnap does not export the described motion sequence or create the chair.'},
      {id:'appearance',title:'Appearance-heavy → body instructions',before:'A confident person in a black jacket, cinematic lighting, an 85 mm camera, 8K, with the right arm raised.',after:'A person is standing confidently with the right arm raised and the left hand resting on the waist. The torso stays upright.',note:'The raised right arm is retained. The waist placement is an optional creative addition. Clothing, lighting and camera rendering stay outside the body prompt.'}
    ]
  }),
  topic('troubleshoot','When a result needs another pass','Use the preview, Understood changes and Text notes together. Planner acceptance checks interpretation and supported operations; it does not establish the visual quality of a generated pose.',{
    bullets:[
      'Too symmetric or generic: add one meaningful weight shift or contrasting arm position, then preview again. Preserve symmetry if it is intentional.',
      'A detail is missing: make that actor, side and final movement explicit. Remove competing details before adding more instructions.',
      'The wrong person moves: separate Person 1 and Person 2 directions into clear sentences. Avoid “her” or “his” when ownership is ambiguous.',
      'A hand stays relaxed: check Approximate hand shapes, name its side, and use a supported gesture. Inspect the fingers after fitting.',
      'Support or contacts fail: check for contradictory floor or partner requirements. A different valid choice may help; exact palm, knee and prop placement belongs in Pose Studio.',
      'No new distinct choices: More like this excludes the previous batch. Try another batch or simplify the direction; accepted results remain available.',
      'Exact angles, a small joint correction or preserving an existing pose: open the accepted result in Pose Studio. A new text generation cannot promise that unrelated joints remain identical.'
    ]
  }),
  topic('skill','Use ChatGPT or another LLM to write a prompt','Give the standalone SKILL.md to your chosen LLM, then describe your idea in ordinary words. Ask it to use the skill and produce a PoseSnap prompt. It should expand a clear request immediately and ask only when an important detail is ambiguous.',{
    paragraphs:[
      'Copy LLM skill copies the entire self-contained Markdown file. Paste it into a conversation, or attach the delivered SKILL.md. Then try “A confident pose” or “A playful dance with the left arm down”. The helper expands the physical action, including important arm-chain and support details, and returns one English prompt with required settings and disclosed assumptions.',
      'Paste only the pose prompt into Your direction. Set character count and Approximate hand shapes separately. The helper should explain unsupported requests instead of promising facial output, reference-image matching or an edit of the current accepted pose.',
      'External LLM suggestions are still suggestions. Review added creative details and inspect the generated body. Reading this offline guide or copying its content does not call an online service or send your prompt.'
    ],skill:true
  }),
  topic('sources','Sources and research notes','Reviewed 25 October 2026. This guide combines NVIDIA’s prompting recommendations with PoseSnap’s current planner, hand composer, support fitter and creation-only workflow.',{
    paragraphs:[
      'NVIDIA recommends a clear human subject, moderate detail, one or two behaviors, and self-contained descriptions. The public BONES-SEED card illustrates natural-language motion descriptions. This guide’s pose examples are original; no motion dataset is downloaded or included.',
      'PoseSnap’s static selection, anatomical checks, hand toggle and supported contacts are app-specific. Official Kimodo animation, timeline and native constraint controls are not exposed here. Prompt examples have semantic planner checks; this is not a claim that every model output or every external LLM has been qualified.'
    ],sources:[
      {title:'NVIDIA · Kimodo best practices',url:'https://research.nvidia.com/labs/sil/projects/kimodo/docs/key_concepts/limitations.html'},
      {title:'NVIDIA · Kimodo-SOMA-RP-v1.2 model card',url:'https://huggingface.co/nvidia/Kimodo-SOMA-RP-v1.2'},
      {title:'BONES-SEED · Natural-language descriptions',url:'https://huggingface.co/datasets/bones-studio/seed#natural-language-descriptions'}
    ]
  })
];
