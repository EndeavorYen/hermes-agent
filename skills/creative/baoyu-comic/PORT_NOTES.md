# Port Notes — baoyu-comic

Ported from [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills) v1.56.1.

## Changes from upstream

### SKILL.md adaptations

| Change | Upstream | Hermes |
|--------|----------|--------|
| Metadata namespace | `openclaw` | `hermes` (with `tags` + `homepage`) |
| Trigger | Slash commands / CLI flags | Natural language skill matching |
| User config | EXTEND.md file (project/user/XDG paths) | Removed — not part of Hermes infra |
| User prompts | `AskUserQuestion` (batched) | `clarify` tool (one question at a time) |
| Image generation | baoyu-imagine (Bun/TypeScript, supports `--ref`) | `image_generate` with text prompts, optional reference images, and URL/local-path results; agent must save the result to the output directory |
| PDF assembly | `scripts/merge-to-pdf.ts` (Bun + `pdf-lib`) | Removed — the PDF merge step is out of scope for this port; pages are delivered as PNGs only |
| Platform support | Linux/macOS/Windows/WSL/PowerShell | Linux/macOS only |
| File operations | Generic instructions | Hermes file tools (`write_file`, `read_file`) |

### Structural removals

- **`references/config/` directory** (removed entirely):
  - `first-time-setup.md` — blocking first-time setup flow for EXTEND.md
  - `preferences-schema.md` — EXTEND.md YAML schema
  - `watermark-guide.md` — watermark config (tied to EXTEND.md)
- **`scripts/` directory** (removed entirely): upstream's `merge-to-pdf.ts` depended on `pdf-lib`, which is not declared anywhere in the Hermes repo. Rather than add a new dependency, the port drops PDF assembly and delivers per-page PNGs.
- **Workflow Step 8 (Merge to PDF)** removed from `workflow.md`; Step 9 (Completion report) renumbered to Step 8.
- **Workflow Step 1.1** — "Load Preferences (EXTEND.md)" section removed from `workflow.md`; steps 1.2/1.3 renumbered to 1.1/1.2.
- **Generic "User Input Tools" and "Image Generation Tools" preambles** — SKILL.md no longer lists fallback rules for multiple possible tools; it references `clarify` and `image_generate` directly.

### Image generation strategy changes

`image_generate`'s schema accepts `prompt`, `aspect_ratio` (`landscape` | `portrait` | `square`), optional `reference_images`, `action`, and `input_fidelity`. Upstream's reference-image flow (`--ref characters.png` for character consistency, plus user-supplied refs for style/palette/scene) now maps to Hermes when the reference is a current-turn image, configured `local_ref:name`, or allowlisted absolute path, so the workflow keeps both direct visual references and textual reproducibility:

- **Character sheet PNG** is still generated for multi-page comics as a **human-facing review artifact** (for visual verification) and a reference for later regenerations / manual prompt edits. When it is current-turn/configured/allowlisted, it can also be passed to `image_generate` as a visual reference.
- **User-supplied reference images** are passed through whenever possible for style / palette / scene anchoring; extracted traits are also embedded in the prompt body for auditability and fallback.
- **Page prompts** still mandate that character descriptions are embedded inline (copied from `characters/characters.md`) so the written contract remains reproducible even when a visual reference is unavailable.
- **Save step** — after every `image_generate` call, the returned URL or local path is saved into the comic output directory and verified before the workflow advances.

### SKILL.md reductions

- CLI option columns (`--art`, `--tone`, `--layout`, `--aspect`, `--lang`, `--ref`, `--storyboard-only`, `--prompts-only`, `--images-only`, `--regenerate`) converted to plain-English option descriptions.
- Preset files (`presets/*.md`) and `ohmsha-guide.md`: `` `--style X` `` / `` `--art X --tone Y` `` shorthand rewritten to `art=X, tone=Y` + natural-language references.
- `partial-workflows.md`: per-skill slash command invocations rewritten as user-intent cues; PDF-related outputs removed.
- `auto-selection.md`: priority order dropped the EXTEND.md tier.
- `analysis-framework.md`: language-priority comment updated (user option → conversation → source).

### File naming convention

Source content pasted by the user is saved as `source-{slug}.md`, where `{slug}` is the kebab-case topic slug used for the output directory. Backups follow the same pattern with a `-backup-YYYYMMDD-HHMMSS` suffix. SKILL.md and `workflow.md` now agree on this single convention.

### What was preserved verbatim

- All 6 art-style definitions (`references/art-styles/`)
- All 7 tone definitions (`references/tones/`)
- All 7 layout definitions (`references/layouts/`)
- Core templates: `character-template.md`, `storyboard-template.md`, `base-prompt.md`
- Preset bodies (only the first few intro lines adapted; special rules unchanged)
- Author, version, homepage attribution

## Syncing with upstream

To pull upstream updates:

```bash
# Compare versions
curl -sL https://raw.githubusercontent.com/JimLiu/baoyu-skills/main/skills/baoyu-comic/SKILL.md | head -5
# Look for the version: line

# Diff a reference file
diff <(curl -sL https://raw.githubusercontent.com/JimLiu/baoyu-skills/main/skills/baoyu-comic/references/art-styles/manga.md) \
     references/art-styles/manga.md
```

Art-style, tone, and layout reference files can usually be overwritten directly (they're upstream-verbatim). `SKILL.md`, `references/workflow.md`, `references/partial-workflows.md`, `references/auto-selection.md`, `references/analysis-framework.md`, `references/ohmsha-guide.md`, and `references/presets/*.md` must be manually merged since they contain Hermes-specific adaptations.

If upstream adds a Hermes-compatible PDF merge step (no extra npm deps), restore `scripts/` and reintroduce Step 8 in `workflow.md`.
