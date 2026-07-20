# Story Video Engine-Aware Tone Map Design

## Outcome

Make multi-character story-video speech more expressive without weakening the
existing guarantees for pronunciation, speaker routing, long-form continuity,
or final-video delivery. Each dialogue utterance may resolve to one controlled
tone plus a small set of delivery modifiers. The resolved control is adapted to
the selected Qwen engine, recorded in the narration manifest, and quality
checked per voice chunk.

The operator continues to provide ordinary story text and an optional cast map.
Tone syntax is optional. Existing projects with no tone data remain neutral and
produce the same synthesis calls as before. The neutral adapter is a strict
no-op: it adds no instruction and does not override the locked voice profile.

## Current Evidence And Gap

The project-local `dialogue_ledger.json` already carries `emotion`, `action`,
and `pace` per utterance. The narration generator preserves those values on
voice chunks, but synthesis currently applies only the cast member's fixed
`variant` such as speed, pitch shift, and broad `expressiveness`. Emotion and
action therefore affect subtitles and audit data more reliably than the actual
performance.

The two Qwen paths expose different control surfaces:

- `qwen_custom_voice` uses a named preset speaker. Qwen 1.7B CustomVoice and
  the installed MLX-Audio runtime accept an optional natural-language
  `instruct` for emotion and style.
- `qwen_full_icl` uses a Base model with reference audio and its exact
  transcript. It does not expose equivalent reliable instruction control, so
  clone performance must rely on speakable text, phrase boundaries, pauses,
  bounded sampling changes, and conservative pacing.

A single parameter table shared by both engines would misrepresent these
capabilities and could make clone voices unstable.

## Considered Approaches

1. **Engine-aware tone catalog and adapters — selected.** Resolve one semantic
   tone, then let each engine adapter use only controls it supports. This gives
   CustomVoice real instruction control while keeping full-ICL clone changes
   conservative and auditable.
2. **One shared speed/pitch/temperature table — rejected.** It is easy to
   implement but produces weak emotional differences, encourages unnatural
   post-process pitch shifting, and ignores CustomVoice instruction support.
3. **One reference recording per emotion — deferred.** A clone tone bank could
   improve strong emotion while preserving a personal voice, but it requires
   approved recordings, exact transcripts, profile versioning, and separate
   acoustic validation. It is a later enhancement, not a v1 prerequisite.

## Tone Contract

Each utterance resolves to a project-local object shaped like:

```json
{
  "tone_id": "adult.desirous",
  "intensity": 2,
  "modifiers": ["whispered", "restrained"],
  "resolution": "mapped",
  "source": {
    "emotion": "desirous",
    "action": "靠近對方耳邊，壓低聲音",
    "pace": "slow"
  }
}
```

`intensity` is an integer from 1 to 3. It selects bounded variants within the
same tone; it is not a free-form multiplier. Resolution precedence is:

1. an explicit valid `tone_id` and modifiers;
2. deterministic mapping from `emotion`, `action`, and `pace`;
3. `general.neutral`.

An invalid explicit tone fails compilation. An unknown automatically generated
emotion falls back to neutral with a manifest warning. The compiler never
guesses an adult tone from punctuation alone.

### General tones

| Tone ID | Visible concept | Intended delivery |
| --- | --- | --- |
| `general.neutral` | 自然 | clear, stable, unmarked |
| `general.warm` | 溫暖 | gentle, close, slightly slower |
| `general.joyful` | 開心 | bright, smiling, light rhythm |
| `general.excited` | 興奮 | energetic, faster, short pauses |
| `general.sad` | 難過 | subdued, slower, longer pauses |
| `general.angry` | 生氣 | firm, precise articulation |
| `general.tense` | 緊張 | restrained, short phrases |
| `general.puzzled` | 疑惑 | hesitant, questioning cadence |

### Adult-only tones

Adult tones use a separate namespace and are valid only when the story content
profile is `adult_explicit`. This is a semantic consistency gate, not an
operator-setup blocker and not an image-generation requirement. Adult black-
subtitle production remains able to proceed through voice and render when its
normal content profile is active.

| Tone ID | Visible concept | Intended delivery |
| --- | --- | --- |
| `adult.flirtatious` | 挑逗 | confident, light, smiling |
| `adult.intimate` | 親密 | warm, close, soft |
| `adult.desirous` | 渴望 | lower, restrained, gradually rising |
| `adult.breathless` | 氣息急促 | shorter phrases, bounded irregular pauses |
| `adult.shy` | 害羞 | quiet, hesitant, slightly slower |
| `adult.teasing` | 戲弄 | playful rhythm and smiling endings |
| `adult.commanding` | 強勢 | steady, deliberate, clearly articulated |
| `adult.receptive` | 接受 | soft, responsive, lower force |
| `adult.intense` | 強烈 | urgent and high-energy within hard bounds |
| `adult.afterglow` | 餘韻 | relaxed, affectionate, even breathing |

`adult.breathless` changes phrase length and bounded pause timing only. It does
not inject breathing, gasps, or any other untranscribed sound.

### Delivery modifiers

The v1 modifier set is deliberately small:

```text
whispered  breathy  trembling  restrained
urgent     hesitant soft       firm
```

Modifiers refine a tone but do not replace it. The catalog defines compatible
tone/modifier pairs; unsupported combinations fail compilation rather than
silently changing meaning. Concrete sexual acts remain `action` presentation
data and are never encoded as tones.

### Delivery pace

Every resolved tone carries one canonical pace: `slow`, `measured`, `natural`,
or `quick`. Pace is a catalog-owned delivery overlay with engine-specific,
bounded speed and pause controls. `natural` has empty adapters and changes
nothing by itself. `slow`, `measured`, and `quick` are auditable applications;
CustomVoice adds only stable Traditional Chinese catalog fragments, while
full-ICL never receives an instruction. Only neutral with no modifiers and
natural pace is the strict neutral no-op.

## Engine Adapters

### Qwen CustomVoice

The adapter maps each tone/modifier combination to a short, versioned
Traditional Chinese instruction template. Templates are catalog data, not
LLM-generated text. For example, a resolved `adult.desirous` plus `whispered`
may produce an instruction equivalent to "帶著壓抑的渴望，靠近並輕聲說，保持自然咬字".

The adapter passes the instruction through `generate_custom_voice(...,
instruct=...)`. It may also apply bounded temperature, speed, and pause values.
If the loaded CustomVoice model cannot accept instructions, any non-neutral
tone fails with a concrete capability error; it does not silently synthesize a
neutral line and label it emotional.

### Qwen full-ICL clone

The adapter continues to pass exact `ref_audio` and `ref_text` and never sends
an unsupported emotion instruction. It controls delivery through:

- speakability-safe phrase boundaries and punctuation;
- explicit pauses with a maximum duration;
- speed and sampling values close to the locked profile baseline;
- the existing restrained, natural, lively, and dramatic expressiveness bands.

For v1, post-process pitch shift remains zero for tone expression. This avoids
turning emotional variation into a different-sounding character. A later
approved clone tone bank may associate several immutable full-ICL references
with one stable voice identity, but it is outside this change.

### Safe bounds

- resolved speed multiplier: `0.90` through `1.10`;
- per-tone temperature delta from profile baseline: `-0.10` through `+0.10`;
- ordinary intra-line pause: `0.08` through `0.35` seconds;
- ellipsis pause: at most `0.45` seconds unless the script carries an explicit
  dramatic-pause directive;
- tone pitch shift: `0` semitones in v1.

The selected values are catalog defaults to be calibrated through audio
fixtures; generated stories cannot write arbitrary synthesis parameters.

## Speakability And Continuity

`display_text` remains the exact subtitle source. `spoken_text` remains the
only lexical input to TTS and pronunciation QC. Character names, emotions, and
actions may enrich `visual_text`, but are not spoken.

The compiler normalizes repeated dots and Unicode ellipses into bounded pause
directives. It preserves meaningful hesitation without allowing `......` to
create multi-second silence. It may add speakability punctuation only to
`spoken_text`; source-preservation modes keep `display_text` untouched.

Adjacent short utterances from the same speaker may share one synthesis chunk
only when tone and modifiers match. A speaker change, action beat, or material
tone change creates a boundary. This avoids both extremes: resetting prosody
for every tiny fragment and flattening a whole emotional turn into one call.

Tone selection considers the preceding resolved tone so an automatically
mapped line does not jump from low-energy sadness directly to high-intensity
joy without an explicit narrative cue. This continuity rule may reduce
automatic intensity by one level; it never overrides an explicit tone.

## Vocalizations

Tone control must not secretly add laughs, sighs, gasps, breathing, or other
non-lexical sounds. If the source explicitly contains a lexical vocalization
such as `嗯` or `啊`, it remains part of `spoken_text` and is covered by the
normal transcript contract. Dedicated generated vocalization segments and a
separate sound-effect library are non-goals for v1 because they need different
ASR and acoustic QC semantics.

## Manifest And Audit Evidence

Every generated voice chunk records:

- catalog schema/version and SHA-256;
- requested and resolved tone, intensity, and modifiers;
- resolution source and any fallback warning;
- engine adapter and exact instruction template identifier, when applicable;
- applied speed, pause, sampling, and pitch values;
- candidate count, selected candidate, and rejection reasons;
- pronunciation, alignment, prosody, and speaker-routing status.

`tone_control_status=PASS` proves that the intended catalog controls were
applied within bounds. Acoustic evidence may report `HEURISTIC_PASS`, but must
not claim human-perceived emotion was proven solely from temperature, pitch,
RMS, or metadata. This keeps the quality report honest.

## Candidate And Quality Policy

Neutral and low-intensity lines generate one candidate. Non-neutral lines at
intensity 2 or 3 may generate two candidates. A third attempt is permitted
only when pronunciation, alignment, duration, or hard prosody checks reject
both initial candidates.

Selection order is:

1. correct and complete speech;
2. locked speaker/profile routing;
3. acceptable duration, silence, and prosody bounds;
4. tone acoustic evidence and scene continuity.

An expressive candidate never wins over a candidate with correct
pronunciation. Failed chunks are regenerated individually. Existing accepted
chunks and their hashes remain unchanged during repair.

## Operator Interface And Help

Natural language remains primary. Examples include:

```text
小美帶著疑惑問：「你真的看見了嗎？」
這一句用比較溫柔、壓低聲音的方式說。
成人黑底字幕影片；這句是親密、帶點害羞，不要把動作念出來。
```

The audio director compiles those requests into controlled IDs. Advanced users
may specify `general.warm` or `adult.intimate`, but internal IDs are optional.
`/story-video help` lists the available concepts, explains that actions are
visible but not spoken, and states that adult tones require an adult-explicit
story profile.

## Failure And Compatibility Policy

- Existing dialogue ledgers without tone fields remain valid and neutral.
- Invalid explicit tone, invalid intensity, incompatible modifier, or adult
  tone in a non-adult project fails before synthesis.
- Missing CustomVoice instruction capability fails a non-neutral CustomVoice
  line with an engine capability error.
- Full-ICL clone synthesis never pretends to support `instruct`; it uses the
  bounded clone adapter.
- Unknown automatic emotions fall back to neutral with an auditable warning.
- Tone processing does not authorize content, image generation, external TTS,
  network fallback, or Slack delivery by itself.
- Private scripts, generated audio, adult content, provider output, and tone
  evaluation artifacts remain local runtime data and are not committed.

## Testing And Completion Evidence

Behavior-focused tests must prove:

1. deterministic mapping of general and adult emotions/actions to controlled
   tone objects;
2. namespace gating without reintroducing an `adult_explicit` setup blocker;
3. CustomVoice sends the expected stable `instruct` while full-ICL clone sends
   `ref_audio` and `ref_text` but no emotion instruction;
4. display/action labels never enter `spoken_text`;
5. ellipsis and pause normalization cannot create an unbounded gap;
6. tone bounds and incompatible modifiers fail before synthesis;
7. candidate selection always prioritizes pronunciation and routing;
8. manifests preserve resolved controls, evidence, and catalog hashes;
9. legacy neutral projects keep their previous call shape and output contract.

After focused and wider suites pass, run a local audio comparison using the
same short Traditional Chinese lines across neutral, warm/puzzled, and one
adult-only tone for a CustomVoice speaker, plus neutral and bounded emotional
delivery for the clone narrator. The smoke must preserve pronunciation and
speaker routing, show bounded timing differences, and produce an honest tone
evidence report. No generated media or private script text is committed.

## Non-goals

- training or fine-tuning an emotion classifier or TTS model;
- unrestricted LLM-generated synthesis instructions;
- automatic explicit-scene classification from punctuation alone;
- generated non-lexical vocalizations or a sound-effect library;
- clone emotion reference-bank creation in v1;
- changing subtitle wording, character casting, visual mode, or delivery
  authorization;
- claiming objective emotional correctness without acoustic or human evidence.
