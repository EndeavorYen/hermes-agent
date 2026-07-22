# Story-video adult source passthrough

`adult_explicit` remains reserved for model-authored or model-expanded content. The
only active adult path is a narrow source passthrough for an already completed
user-supplied screenplay.

The path is active only when all of these conditions hold:

- the request explicitly identifies the source as NSFW or adult content;
- the complete screenplay is supplied in a fenced text block;
- every spoken character has an explicit voice mapping;
- `visual_mode=black_subtitle`;
- image providers are empty and image generation stays forbidden;
- TTS is offline local Qwen and rendering is local deterministic rendering.

Ingest is deterministic. It selects one screenplay block, removes exact and
near-identical duplicate blocks, separates spoken text from stage directions, preserves source
references, and hash-locks the source, display script, cast, and dialogue ledger.
It does not ask an LLM to rewrite, expand, sanitize, or reclassify the source.

The planning gate recognizes only the exact
`adult-explicit-local-passthrough-v1` profile and verifies the local-only provider
boundary, source hashes, speaker and utterance counts, and compiled dubbing
contract. A forged or modified profile fails closed. Adult image generation,
external media providers, missing voice mappings, and non-fenced source requests
remain `SETUP_REQUIRED`.

Stateful story-video tools accept the pair `run_id + project_dir` as verified
recovery identity. This lets a rotated Codex/MCP session recover the same run
without guessing from recency or topic.
