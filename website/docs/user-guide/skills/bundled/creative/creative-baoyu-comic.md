---
title: "Baoyu Comic — Knowledge comics (知识漫画): educational, biography, tutorial"
sidebar_label: "Baoyu Comic"
description: "Knowledge comics (知识漫画): educational, biography, tutorial"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Baoyu Comic

Knowledge comics (知识漫画): educational, biography, tutorial.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/creative/baoyu-comic` |
| Version | `1.56.1` |
| Author | 宝玉 (JimLiu) |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `comic`, `knowledge-comic`, `creative`, `image-generation` |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Knowledge Comic Creator

Adapted from [baoyu-comic](https://github.com/JimLiu/baoyu-skills) for Hermes Agent's tool ecosystem.

Create original knowledge comics with flexible art style × tone combinations.

## When to Use

Trigger this skill when the user asks to create a knowledge/educational comic, biography comic, tutorial comic, or uses terms like "知识漫画", "教育漫画", or "Logicomix-style". The user provides content (text, file path, URL, or topic) and optionally specifies art style, tone, layout, aspect ratio, or language.

## Reference Images

Hermes' `image_generate` tool accepts a text prompt, aspect ratio, and optional reference images. When the user supplies reference images, pass real image references through whenever the current backend supports them (for example OpenAI / Codex-backed GPT Image 2), and keep text trait extraction as a fallback/provenance aid rather than a replacement for the pixels.

**Intake**: Accept file paths when the user provides them (or pastes images in conversation).
- File path(s) → copy to `refs/NN-ref-{slug}.{ext}` alongside the comic output for provenance; pass as `reference_images` when the path is a current-turn upload, a configured `local_ref:name`, or an allowlisted absolute local reference
- Pasted image with no path → use `current_turn_images` / `current_turn_image:N` when available; otherwise ask the user for the path via `clarify`, or extract style traits verbally as a fallback
- No reference → skip this section

**Usage modes** (per reference):

| Usage | Effect |
|-------|--------|
| `style` | Extract style traits (line treatment, texture, mood) and append to every page's prompt body |
| `palette` | Extract hex colors and append to every page's prompt body |
| `scene` | Extract scene composition or subject notes and append to the relevant page(s) |

When a reference is active for a page, call `image_generate` with `action="edit"` (or leave `action="auto"` when using current-turn defaults) and `input_fidelity="high"` for identity, product, outfit, layout, or style preservation.

**Record in each page's prompt frontmatter** when refs exist:

```yaml
references:
  - ref_id: 01
    filename: 01-ref-scene.png
    usage: style
    traits: "muted earth tones, soft-edged ink wash, low-contrast backgrounds"
```

Character consistency starts with **text descriptions** in `characters/characters.md` (written in Step 3) embedded inline in every page prompt (Step 5). When a character sheet or user-supplied reference is available as a current-turn/configured/allowlisted reference, also pass it to `image_generate` so GPT Image 2 can preserve the visual traits directly.

## Options

### Visual Dimensions

| Option | Values | Description |
|--------|--------|-------------|
| Art | ligne-claire (default), manga, realistic, ink-brush, chalk, minimalist | Art style / rendering technique |
| Tone | neutral (default), warm, dramatic, romantic, energetic, vintage, action | Mood / atmosphere |
| Layout | standard (default), cinematic, dense, splash, mixed, webtoon, four-panel | Panel arrangement |
| Aspect | 3:4 (default, portrait), 4:3 (landscape), 16:9 (widescreen) | Page aspect ratio |
| Language | auto (default), zh, en, ja, etc. | Output language |
| Refs | File paths | Reference images used directly when possible, with style / palette trait extraction kept as a fallback. See [Reference Images](#reference-images) above. |

### Partial Workflow Options

| Option | Description |
|--------|-------------|
| Storyboard only | Generate storyboard only, skip prompts and images |
| Prompts only | Generate storyboard + prompts, skip images |
| Images only | Generate images from existing prompts directory |
| Regenerate N | Regenerate specific page(s) only (e.g., `3` or `2,5,8`) |

Details: [references/partial-workflows.md](https://github.com/NousResearch/hermes-agent/blob/main/skills/creative/baoyu-comic/references/partial-workflows.md)

### Art, Tone & Preset Catalogue

- **Art styles** (6): `ligne-claire`, `manga`, `realistic`, `ink-brush`, `chalk`, `minimalist`. Full definitions at `references/art-styles/<style>.md`.
- **Tones** (7): `neutral`, `warm`, `dramatic`, `romantic`, `energetic`, `vintage`, `action`. Full definitions at `references/tones/<tone>.md`.
- **Presets** (5) with special rules beyond plain art+tone:

  | Preset | Equivalent | Hook |
  |--------|-----------|------|
  | `ohmsha` | manga + neutral | Visual metaphors, no talking heads, gadget reveals |
  | `wuxia` | ink-brush + action | Qi effects, combat visuals, atmospheric |
  | `shoujo` | manga + romantic | Decorative elements, eye details, romantic beats |
  | `concept-story` | manga + warm | Visual symbol system, growth arc, dialogue+action balance |
  | `four-panel` | minimalist + neutral + four-panel layout | 起承转合 structure, B&W + spot color, stick-figure characters |

  Full rules at `references/presets/<preset>.md` — load the file when a preset is picked.

- **Compatibility matrix** and **content-signal → preset** table live in [references/auto-selection.md](https://github.com/NousResearch/hermes-agent/blob/main/skills/creative/baoyu-comic/references/auto-selection.md). Read it before recommending combinations in Step 2.

## File Structure

Output directory: `comic/{topic-slug}/`
- Slug: 2-4 words kebab-case from topic (e.g., `alan-turing-bio`)
- Conflict: append timestamp (e.g., `turing-story-20260118-143052`)

**Contents**:
| File | Description |
|------|-------------|
| `source-{slug}.md` | Saved source content (kebab-case slug matches the output directory) |
| `analysis.md` | Content analysis |
| `storyboard.md` | Storyboard with panel breakdown |
| `characters/characters.md` | Character definitions |
| `characters/characters.png` | Character reference sheet (downloaded from `image_generate`) |
| `prompts/NN-{cover\|page}-[slug].md` | Generation prompts |
| `NN-{cover\|page}-[slug].png` | Generated images (downloaded from `image_generate`) |
| `refs/NN-ref-{slug}.{ext}` | User-supplied reference images (optional, for provenance) |

## Language Handling

**Detection Priority**:
1. User-specified language (explicit option)
2. User's conversation language
3. Source content language

**Rule**: Use user's input language for ALL interactions:
- Storyboard outlines and scene descriptions
- Image generation prompts
- User selection options and confirmations
- Progress updates, questions, errors, summaries

Technical terms remain in English.

## Workflow

### Progress Checklist

```
Comic Progress:
- [ ] Step 1: Setup & Analyze
  - [ ] 1.1 Analyze content
  - [ ] 1.2 Check existing directory
- [ ] Step 2: Confirmation - Style & options ⚠️ REQUIRED
- [ ] Step 3: Generate storyboard + characters
- [ ] Step 4: Review outline (conditional)
- [ ] Step 5: Generate prompts
- [ ] Step 6: Review prompts (conditional)
- [ ] Step 7: Generate images
  - [ ] 7.1 Generate character sheet (if needed) → characters/characters.png
  - [ ] 7.2 Generate pages (with character descriptions embedded in prompt)
- [ ] Step 8: Completion report
```

### Flow

```
Input → Analyze → [Check Existing?] → [Confirm: Style + Reviews] → Storyboard → [Review?] → Prompts → [Review?] → Images → Complete
```

### Step Summary

| Step | Action | Key Output |
|------|--------|------------|
| 1.1 | Analyze content | `analysis.md`, `source-{slug}.md` |
| 1.2 | Check existing directory | Handle conflicts |
| 2 | Confirm style, focus, audience, reviews | User preferences |
| 3 | Generate storyboard + characters | `storyboard.md`, `characters/` |
| 4 | Review outline (if requested) | User approval |
| 5 | Generate prompts | `prompts/*.md` |
| 6 | Review prompts (if requested) | User approval |
| 7.1 | Generate character sheet (if needed) | `characters/characters.png` |
| 7.2 | Generate pages | `*.png` files |
| 8 | Completion report | Summary |

### User Questions

Use the `clarify` tool to confirm options. Since `clarify` handles one question at a time, ask the most important question first and proceed sequentially. See [references/workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/skills/creative/baoyu-comic/references/workflow.md) for the full Step 2 question set.

**Timeout handling (CRITICAL)**: `clarify` can return `"The user did not provide a response within the time limit. Use your best judgement to make the choice and proceed."` — this is NOT user consent to default everything.

- Treat it as a default **for that one question only**. Continue asking the remaining Step 2 questions in sequence; each question is an independent consent point.
- **Surface the default to the user visibly** in your next message so they have a chance to correct it: e.g. `"Style: defaulted to ohmsha preset (clarify timed out). Say the word to switch."` — an unreported default is indistinguishable from never having asked.
- Do NOT collapse Step 2 into a single "use all defaults" pass after one timeout. If the user is genuinely absent, they will be equally absent for all five questions — but they can correct visible defaults when they return, and cannot correct invisible ones.

### Step 7: Image Generation

Use Hermes' built-in `image_generate` tool for all image rendering. Its schema accepts `prompt`, `aspect_ratio` (`landscape` | `portrait` | `square`), optional `reference_images`, `action`, and `input_fidelity`. It returns either a URL or an absolute local file path in the `image` field; every generated page or character sheet must end up as a verified file in the output directory.

**Prompt file requirement (hard)**: write each image's full, final prompt to a standalone file under `prompts/` (naming: `NN-{type}-[slug].md`) BEFORE calling `image_generate`. The prompt file is the reproducibility record.

**Aspect ratio mapping** — the storyboard's `aspect_ratio` field maps to `image_generate`'s format as follows:

| Storyboard ratio | `image_generate` format |
|------------------|-------------------------|
| `3:4`, `9:16`, `2:3` | `portrait` |
| `4:3`, `16:9`, `3:2` | `landscape` |
| `1:1` | `square` |

**Save step** — after every `image_generate` call:
1. Read the `image` field from the tool result
2. If it is a URL, fetch the image bytes using an **absolute** output path, e.g.
   `curl -fsSL "<url>" -o /abs/path/to/comic/<slug>/NN-page-<slug>.png`
3. If it is an absolute local path, copy it to the target output path
4. Verify the file exists and is non-empty at that exact path before proceeding to the next page

**Never rely on shell CWD persistence for output paths.** The terminal tool's persistent-shell CWD can change between batches (session expiry, `TERMINAL_LIFETIME_SECONDS`, a failed `cd` that leaves you in the wrong directory). `curl -o relative/path.png` or `cp source relative/path.png` is a silent footgun: if CWD has drifted, the file lands somewhere else with no error. **Always pass a fully-qualified absolute output path**, or pass `workdir=<abs path>` to the terminal tool. Incident Apr 2026: pages 06-09 of a 10-page comic landed at the repo root instead of `comic/<slug>/` because batch 3 inherited a stale CWD from batch 2 and `curl -o 06-page-skills.png` wrote to the wrong directory. The agent then spent several turns claiming the files existed where they didn't.

**7.1 Character sheet** — generate it (to `characters/characters.png`, aspect `landscape`) when the comic is multi-page with recurring characters. Skip for simple presets (e.g., four-panel minimalist) or single-page comics. The prompt file at `characters/characters.md` must exist before invoking `image_generate`. The rendered PNG is a **human-facing review artifact** (so the user can visually verify character design) and can be used as a later visual reference when it is available as a current-turn/configured/allowlisted reference.

**7.2 Pages** — each page's prompt MUST already be at `prompts/NN-{cover|page}-[slug].md` before invoking `image_generate`. Embed character descriptions (sourced from `characters/characters.md`) inline in every page prompt during Step 5, and pass any active page/character/style references with `reference_images` so the image model gets both the written specification and the pixels.

**Backup rule**: existing `prompts/…md` and `…png` files → rename with `-backup-YYYYMMDD-HHMMSS` suffix before regenerating.

Full step-by-step workflow (analysis, storyboard, review gates, regeneration variants): [references/workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/skills/creative/baoyu-comic/references/workflow.md).

## References

**Core Templates**:
- [analysis-framework.md](https://github.com/NousResearch/hermes-agent/blob/main/skills/creative/baoyu-comic/references/analysis-framework.md) - Deep content analysis
- [character-template.md](https://github.com/NousResearch/hermes-agent/blob/main/skills/creative/baoyu-comic/references/character-template.md) - Character definition format
- [storyboard-template.md](https://github.com/NousResearch/hermes-agent/blob/main/skills/creative/baoyu-comic/references/storyboard-template.md) - Storyboard structure
- [ohmsha-guide.md](https://github.com/NousResearch/hermes-agent/blob/main/skills/creative/baoyu-comic/references/ohmsha-guide.md) - Ohmsha manga specifics

**Style Definitions**:
- `references/art-styles/` - Art styles (ligne-claire, manga, realistic, ink-brush, chalk, minimalist)
- `references/tones/` - Tones (neutral, warm, dramatic, romantic, energetic, vintage, action)
- `references/presets/` - Presets with special rules (ohmsha, wuxia, shoujo, concept-story, four-panel)
- `references/layouts/` - Layouts (standard, cinematic, dense, splash, mixed, webtoon, four-panel)

**Workflow**:
- [workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/skills/creative/baoyu-comic/references/workflow.md) - Full workflow details
- [auto-selection.md](https://github.com/NousResearch/hermes-agent/blob/main/skills/creative/baoyu-comic/references/auto-selection.md) - Content signal analysis
- [partial-workflows.md](https://github.com/NousResearch/hermes-agent/blob/main/skills/creative/baoyu-comic/references/partial-workflows.md) - Partial workflow options

## Page Modification

| Action | Steps |
|--------|-------|
| **Edit** | **Update prompt file FIRST** → regenerate image → download new PNG |
| **Add** | Create prompt at position → generate with character descriptions embedded → renumber subsequent → update storyboard |
| **Delete** | Remove files → renumber subsequent → update storyboard |

**IMPORTANT**: When updating pages, ALWAYS update the prompt file (`prompts/NN-{cover|page}-[slug].md`) FIRST before regenerating. This ensures changes are documented and reproducible.

## Pitfalls

- Image generation: 10-30 seconds per page; auto-retry once on failure
- **Always save** the `image_generate` result to a local PNG in the output directory — downstream tooling (and the user's review) expects files there, not ephemeral URLs or cache-only paths
- **Use absolute paths for `curl -o` or `cp` targets** — never rely on persistent-shell CWD across batches. Silent footgun: files land in the wrong directory and subsequent `ls` on the intended path shows nothing. See Step 7 "Save step".
- Use stylized alternatives for sensitive public figures
- **Step 2 confirmation required** - do not skip
- **Steps 4/6 conditional** - only if user requested in Step 2
- **Step 7.1 character sheet** - recommended for multi-page comics, optional for simple presets. The PNG is a review/regeneration aid and may be passed as a visual reference when it is current-turn/configured/allowlisted; page prompts (written in Step 5) still include the text descriptions in `characters/characters.md`
- **Strip secrets** — scan source content for API keys, tokens, or credentials before writing any output file
