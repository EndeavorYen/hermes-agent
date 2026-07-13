# Audience-Adaptive Story-Video Engagement Design

## Problem

Story-video source art can pass factual, anatomical, composition, and subtitle
checks while still feeling like a museum catalog or textbook illustration. The
current contract asks what must be visible, but not what moment makes a viewer
want to see the next shot. Adding words such as `cinematic` or `epic` would
change surface styling without fixing the missing story event.

The solution must be general. A five-year-old dinosaur video, an adult history
documentary, a cooking story, and a product explainer need different kinds of
energy, but all need a readable visual question, event, and consequence.

## Chosen Direction

Use an **audience-adaptive visual storytelling contract** at three levels:

1. The project locks an `audience_profile` and `engagement_profile`.
2. The scene ledger assigns every shot a concrete `story_moment` and a role in
   the local engagement arc.
3. Prompt compilation and OpenAI vision QC enforce those fields from visible
   evidence rather than descriptive adjectives.

This combines factual evidence with narrative energy. It does not require a
recurring host, force every shot to be action-heavy, or sensationalize claims.

## Alternatives Rejected

### Prompt adjectives only

Appending `cinematic`, `dramatic`, or `exciting` is cheap but unreliable. It
often produces prettier lighting around the same passive composition and gives
QC no objective behavior to verify.

### Fixed child host

A recurring child or mascot can improve warmth, but it adds identity continuity,
changes documentary tone, and is unsuitable for many adult or professional
topics. It remains an optional project choice, not the general mechanism.

### Maximum intensity for every shot

Constant spectacle creates fatigue and encourages scientific exaggeration.
The system needs intentional contrast between hook, build, reveal, payoff, and
brief breathing shots.

## Project Contract

Planning records these optional, backward-compatible fields:

```json
{
  "audience_profile": {
    "age_band": "early_childhood|school_age|teen|general|adult|professional",
    "knowledge_level": "newcomer|familiar|advanced",
    "attention_style": "concrete_fast|curious_explorer|reflective|analytical",
    "safety_intensity": "gentle|moderate|standard"
  },
  "engagement_profile": {
    "mode": "young_explorer|discovery_documentary|human_drama|transformation|decision_tension|calm_wonder",
    "energy": "gentle|balanced|high",
    "humor": "none|light|playful",
    "sensationalism_forbidden": true
  }
}
```

If the user specifies an audience, preserve it. Otherwise infer a conservative
profile from the request and production type. Do not silently convert a general
or professional video into children's content.

The current dinosaur project will use:

```json
{
  "audience_profile": {
    "age_band": "early_childhood",
    "knowledge_level": "newcomer",
    "attention_style": "curious_explorer",
    "safety_intensity": "gentle"
  },
  "engagement_profile": {
    "mode": "young_explorer",
    "energy": "balanced",
    "humor": "light",
    "sensationalism_forbidden": true
  }
}
```

## Universal Shot Contract

Each shot adds:

- `engagement_role`: `hook`, `build`, `reveal`, `reaction`, `payoff`, or
  `breathe`;
- `attention_hook`: the visible question, surprise, contrast, discovery, risk,
  transformation, decision, or scale relationship;
- `story_moment`: the exact instant frozen by the image;
- `action_consequence`: what just changed or is about to change;
- `composition_energy`: `calm`, `curious`, `tense`, `kinetic`, or `awe`;
- `viewer_emotion`: the intended visible response, such as curiosity, wonder,
  relief, anticipation, delight, or concern;
- `engagement_criteria`: visible acceptance criteria for the chosen audience;
- `calm_reason`: required only when `engagement_role=breathe`.

Existing ledgers without these fields remain loadable. Before generation, the
compiler deterministically derives a conservative shot moment from the existing
subject, action, evidence, narrative role, and audience profile. Newly planned
projects must write the explicit fields.

## Topic Adaptation

The same contract maps to different visual devices:

| Topic | Suitable tension or wonder |
| --- | --- |
| Science and nature | mechanism in motion, scale surprise, discovery, near consequence, evidence reveal |
| History | human choice, looming change, before/after contrast, object witness |
| Cooking and making | transformation, texture change, timed action, reveal |
| Business and product | decision tension, obstacle removal, visible outcome, comparison |
| Biography | effort, reaction, turning point, meaningful object |
| Calm educational content | curiosity, pattern recognition, gentle reveal, sensory wonder |

The adaptation may change camera and event design, but never invent unsupported
facts, fake danger, or false emotional reactions.

## Prompt Compilation

`compile_shot_prompt` will express the structured moment in production language:

1. State the audience and engagement mode.
2. Describe the frame as a single decisive instant, not a subject inventory.
3. Require a clear foreground, middle-ground event, and directional visual path
   when compatible with the shot.
4. Specify visible action cues: displaced dust, water, fabric, gaze, body lean,
   tool contact, material change, environmental reaction, or scale cue.
5. Preserve evidence, anatomy, continuity, and subtitle-safe constraints.
6. Explain what must remain calm when the shot is an intentional breathing beat.

The compiler must not blindly add every device. It chooses two or three that
fit the shot contract and scientific confidence.

## Sequence Rhythm

Single-image quality is insufficient. The planner and phase gate enforce:

- no more than one unreasoned `breathe` shot in any three-shot window;
- no more than two consecutive shots with the same engagement role,
  composition energy, scale, or visual device unless justified;
- every 20-30 seconds includes a hook, reveal, reaction, payoff, or meaningful
  visual turn;
- calm shots prepare or resolve an energetic beat rather than filling time.

## Vision QC

Add two scored dimensions while retaining factual and production checks:

- `narrative_engagement`: does the image contain a visible event, question,
  discovery, contrast, or consequence suitable for the audience?
- `story_moment_clarity`: can a viewer understand what is happening and where
  to look in one glance?

Add typed blocker codes:

- `static_catalog`: passive specimen, lineup, posed subject, or generic scenery
  without an intentional calm reason;
- `missing_story_moment`: the declared instant or consequence is not visible;
- `flat_composition`: no depth, directional path, scale cue, or focal hierarchy;
- `audience_mismatch`: intensity, abstraction, humor, or fear is wrong for the
  locked audience;
- `sensationalized_claim`: excitement depends on unsupported danger, behavior,
  anatomy, or certainty.

An intentional `breathe` shot may pass with low kinetic energy, but it must
still have visual curiosity, a clear focal hierarchy, and a recorded reason.

Repair planning uses these blocker codes. For example, `static_catalog` changes
the event and camera relationship; it does not merely relight or recrop the
same arrangement.

## Skill Changes

Update `story-video-script-director` to make audience, engagement arc, and shot
story moments part of planning and script-quality proof.

Update `story-video-production-pipeline` to make audience-adaptive engagement a
general source-art and QC gate. The default remains evidence-led documentary,
but evidence must be presented as a meaningful visual event.

Keep detailed profile examples in a reference file so the active skill remains
concise. The skills must describe principles and routing, while schemas and
tests enforce exact behavior.

## Current Project Migration

1. Keep all existing artifacts and attempt history.
2. Lock the dinosaur project's audience to early childhood and mode to
   `young_explorer`.
3. Upgrade remaining ungenerated ledger shots with explicit engagement fields.
4. Run vision engagement audit over selected images.
5. Mark only images with engagement blockers for selective regeneration.
6. Use one generated candidate per repair round and preserve OpenAI-only routing.

This avoids blind full-batch regeneration while allowing dull selected images
to be replaced when visual evidence proves the need.

## Verification

TDD coverage will prove:

- audience profiles remain general and do not default every project to children;
- old ledgers compile through deterministic compatibility defaults;
- new prompts contain a concrete story moment, not adjective-only energy;
- intentional calm shots are allowed with `calm_reason`;
- static catalog and audience mismatch findings drive typed repair strategies;
- sequence rhythm rejects repeated passive beats;
- current project migration preserves selected assets and attempt history;
- story-video image generation and judging remain OpenAI-only.

Live validation will compare one current passive evidence shot and one creature
shot against audience-adaptive replacements. OpenAI vision must score the new
images for factual credibility, subtitle safety, narrative engagement, and
story-moment clarity. Only the winning current artifacts enter the project.

## Resource Policy

- One candidate per shot or repair round.
- No speculative candidate grids.
- Audit existing images before regeneration.
- Stop when the image passes all hard blockers and the engagement threshold.
- Never trade factual credibility or child safety for energy.
