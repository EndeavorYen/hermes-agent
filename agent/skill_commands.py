"""Shared slash command helpers for skills.

Shared between CLI (cli.py) and gateway (gateway/run.py) so both surfaces
can invoke skills via /skill-name commands.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_constants import display_hermes_home
from agent.skill_preprocessing import (
    expand_inline_shell as _expand_inline_shell,
    load_skills_config as _load_skills_config,
    substitute_template_vars as _substitute_template_vars,
)

logger = logging.getLogger(__name__)

_skill_commands: Dict[str, Dict[str, Any]] = {}
_skill_command_aliases: Dict[str, str] = {}
_PLAN_SLUG_RE = re.compile(r"[^a-z0-9]+")
# Patterns for sanitizing skill names into clean hyphen-separated slugs.
_SKILL_INVALID_CHARS = re.compile(r"[^a-z0-9-]")
_SKILL_MULTI_HYPHEN = re.compile(r"-{2,}")

def build_plan_path(
    user_instruction: str = "",
    *,
    now: datetime | None = None,
) -> Path:
    """Return the default workspace-relative markdown path for a /plan invocation.

    Relative paths are intentional: file tools are task/backend-aware and resolve
    them against the active working directory for local, docker, ssh, modal,
    daytona, and similar terminal backends. That keeps the plan with the active
    workspace instead of the Hermes host's global home directory.
    """
    slug_source = (user_instruction or "").strip().splitlines()[0] if user_instruction else ""
    slug = _PLAN_SLUG_RE.sub("-", slug_source.lower()).strip("-")
    if slug:
        slug = "-".join(part for part in slug.split("-")[:8] if part)[:48].strip("-")
    slug = slug or "conversation-plan"
    timestamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    return Path(".hermes") / "plans" / f"{timestamp}-{slug}.md"


def _normalize_skill_slug(value: str) -> str:
    slug = (value or "").strip().lower().replace(" ", "-").replace("_", "-")
    slug = _SKILL_INVALID_CHARS.sub("", slug)
    slug = _SKILL_MULTI_HYPHEN.sub("-", slug).strip("-")
    return slug


def _load_skill_payload(skill_identifier: str, task_id: str | None = None) -> tuple[dict[str, Any], Path | None, str] | None:
    """Load a skill by name/path and return (loaded_payload, skill_dir, display_name)."""
    raw_identifier = (skill_identifier or "").strip()
    if not raw_identifier:
        return None

    try:
        from tools.skills_tool import SKILLS_DIR, skill_view

        identifier_path = Path(raw_identifier).expanduser()
        if identifier_path.is_absolute():
            try:
                normalized = str(identifier_path.resolve().relative_to(SKILLS_DIR.resolve()))
            except Exception:
                normalized = raw_identifier
        else:
            normalized = raw_identifier.lstrip("/")

        loaded_skill = json.loads(
            skill_view(normalized, task_id=task_id, preprocess=False)
        )
    except Exception:
        return None

    if not loaded_skill.get("success"):
        return None

    skill_name = str(loaded_skill.get("name") or normalized)
    skill_path = str(loaded_skill.get("path") or "")
    skill_dir = None
    # Prefer the absolute skill_dir returned by skill_view() — this is
    # correct for both local and external skills.  Fall back to the old
    # SKILLS_DIR-relative reconstruction only when skill_dir is absent
    # (e.g. legacy skill_view responses).
    abs_skill_dir = loaded_skill.get("skill_dir")
    if abs_skill_dir:
        skill_dir = Path(abs_skill_dir)
    elif skill_path:
        try:
            skill_dir = SKILLS_DIR / Path(skill_path).parent
        except Exception:
            skill_dir = None

    return loaded_skill, skill_dir, skill_name


def _inject_skill_config(loaded_skill: dict[str, Any], parts: list[str]) -> None:
    """Resolve and inject skill-declared config values into the message parts.

    If the loaded skill's frontmatter declares ``metadata.hermes.config``
    entries, their current values (from config.yaml or defaults) are appended
    as a ``[Skill config: ...]`` block so the agent knows the configured values
    without needing to read config.yaml itself.
    """
    try:
        from agent.skill_utils import (
            extract_skill_config_vars,
            parse_frontmatter,
            resolve_skill_config_values,
        )

        # The loaded_skill dict contains the raw content which includes frontmatter
        raw_content = str(loaded_skill.get("raw_content") or loaded_skill.get("content") or "")
        if not raw_content:
            return

        frontmatter, _ = parse_frontmatter(raw_content)
        config_vars = extract_skill_config_vars(frontmatter)
        if not config_vars:
            return

        resolved = resolve_skill_config_values(config_vars)
        if not resolved:
            return

        lines = ["", f"[Skill config (from {display_hermes_home()}/config.yaml):"]
        for key, value in resolved.items():
            display_val = str(value) if value else "(not set)"
            lines.append(f"  {key} = {display_val}")
        lines.append("]")
        parts.extend(lines)
    except Exception:
        pass  # Non-critical — skill still loads without config injection


def _build_skill_message(
    loaded_skill: dict[str, Any],
    skill_dir: Path | None,
    activation_note: str,
    user_instruction: str = "",
    runtime_note: str = "",
    session_id: str | None = None,
) -> str:
    """Format a loaded skill into a user/system message payload."""
    from tools.skills_tool import SKILLS_DIR

    content = str(loaded_skill.get("content") or "")

    # ── Template substitution and inline-shell expansion ──
    # Done before anything else so downstream blocks (setup notes,
    # supporting-file hints) see the expanded content.
    skills_cfg = _load_skills_config()
    if skills_cfg.get("template_vars", True):
        content = _substitute_template_vars(content, skill_dir, session_id)
    if skills_cfg.get("inline_shell", False):
        timeout = int(skills_cfg.get("inline_shell_timeout", 10) or 10)
        content = _expand_inline_shell(content, skill_dir, timeout)

    parts = [activation_note, "", content.strip()]

    # ── Inject the absolute skill directory so the agent can reference
    #    bundled scripts without an extra skill_view() round-trip. ──
    if skill_dir:
        parts.append("")
        parts.append(f"[Skill directory: {skill_dir}]")
        parts.append(
            "Resolve any relative paths in this skill (e.g. `scripts/foo.js`, "
            "`templates/config.yaml`) against that directory, then run them "
            "with the terminal tool using the absolute path."
        )

    # ── Inject resolved skill config values ──
    _inject_skill_config(loaded_skill, parts)

    if loaded_skill.get("setup_skipped"):
        parts.extend(
            [
                "",
                "[Skill setup note: Required environment setup was skipped. Continue loading the skill and explain any reduced functionality if it matters.]",
            ]
        )
    elif loaded_skill.get("gateway_setup_hint"):
        parts.extend(
            [
                "",
                f"[Skill setup note: {loaded_skill['gateway_setup_hint']}]",
            ]
        )
    elif loaded_skill.get("setup_needed") and loaded_skill.get("setup_note"):
        parts.extend(
            [
                "",
                f"[Skill setup note: {loaded_skill['setup_note']}]",
            ]
        )

    supporting = []
    linked_files = loaded_skill.get("linked_files") or {}
    for entries in linked_files.values():
        if isinstance(entries, list):
            supporting.extend(entries)

    if not supporting and skill_dir:
        for subdir in ("references", "templates", "scripts", "assets"):
            subdir_path = skill_dir / subdir
            if subdir_path.exists():
                for f in sorted(subdir_path.rglob("*")):
                    if f.is_file() and not f.is_symlink():
                        rel = str(f.relative_to(skill_dir))
                        supporting.append(rel)

    if supporting and skill_dir:
        try:
            skill_view_target = str(skill_dir.relative_to(SKILLS_DIR))
        except ValueError:
            # Skill is from an external dir — use the skill name instead
            skill_view_target = skill_dir.name
        parts.append("")
        parts.append("[This skill has supporting files:]")
        for sf in supporting:
            parts.append(f"- {sf}  ->  {skill_dir / sf}")
        parts.append(
            f'\nLoad any of these with skill_view(name="{skill_view_target}", '
            f'file_path="<path>"), or run scripts directly by absolute path '
            f"(e.g. `node {skill_dir}/scripts/foo.js`)."
        )

    if user_instruction:
        parts.append("")
        parts.append(f"The user has provided the following instruction alongside the skill invocation: {user_instruction}")

    if runtime_note:
        parts.append("")
        parts.append(f"[Runtime note: {runtime_note}]")

    return "\n".join(parts)


def scan_skill_commands() -> Dict[str, Dict[str, Any]]:
    """Scan ~/.hermes/skills/ and return a mapping of /command -> skill info.

    Returns:
        Dict mapping "/skill-name" to {name, description, skill_md_path, skill_dir}.
    """
    global _skill_commands, _skill_command_aliases
    _skill_commands = {}
    _skill_command_aliases = {}
    try:
        from tools.skills_tool import SKILLS_DIR, _parse_frontmatter, skill_matches_platform, _get_disabled_skill_names
        from agent.skill_utils import get_external_skills_dirs, iter_skill_index_files
        disabled = _get_disabled_skill_names()
        seen_names: set = set()

        # Scan local dir first, then external dirs
        dirs_to_scan = []
        if SKILLS_DIR.exists():
            dirs_to_scan.append(SKILLS_DIR)
        dirs_to_scan.extend(get_external_skills_dirs())

        for scan_dir in dirs_to_scan:
            for skill_md in iter_skill_index_files(scan_dir, "SKILL.md"):
                if any(part in ('.git', '.github', '.hub', '.archive') for part in skill_md.parts):
                    continue
                try:
                    content = skill_md.read_text(encoding='utf-8')
                    frontmatter, body = _parse_frontmatter(content)
                    # Skip skills incompatible with the current OS platform
                    if not skill_matches_platform(frontmatter):
                        continue
                    name = frontmatter.get('name', skill_md.parent.name)
                    if name in seen_names:
                        continue
                    # Respect user's disabled skills config
                    if name in disabled:
                        continue
                    description = frontmatter.get('description', '')
                    if not description:
                        for line in body.strip().split('\n'):
                            line = line.strip()
                            if line and not line.startswith('#'):
                                description = line[:80]
                                break
                    seen_names.add(name)
                    cmd_name = _normalize_skill_slug(name)
                    if not cmd_name:
                        continue
                    canonical_key = f"/{cmd_name}"
                    _skill_commands[canonical_key] = {
                        "name": name,
                        "description": description or f"Invoke the {name} skill",
                        "skill_md_path": str(skill_md),
                        "skill_dir": str(skill_md.parent),
                    }

                    hermes_meta = ((frontmatter.get("metadata") or {}).get("hermes") or {})
                    raw_aliases = (
                        hermes_meta.get("aliases")
                        or hermes_meta.get("command_aliases")
                        or []
                    )
                    if isinstance(raw_aliases, str):
                        raw_aliases = [raw_aliases]
                    if isinstance(raw_aliases, list):
                        for alias in raw_aliases:
                            alias_slug = _normalize_skill_slug(str(alias))
                            if not alias_slug or alias_slug == cmd_name:
                                continue
                            alias_key = f"/{alias_slug}"
                            if alias_key in _skill_commands or alias_key in _skill_command_aliases:
                                continue
                            _skill_command_aliases[alias_key] = canonical_key
                except Exception:
                    continue
    except Exception:
        pass
    return _skill_commands


def get_skill_commands() -> Dict[str, Dict[str, Any]]:
    """Return the current skill commands mapping (scan first if empty)."""
    if not _skill_commands:
        scan_skill_commands()
    return _skill_commands


def reload_skills() -> Dict[str, Any]:
    """Re-scan the skills directory and return a diff of what changed.

    Rescans ``~/.hermes/skills/`` and any ``skills.external_dirs`` so the
    slash-command map (``agent.skill_commands._skill_commands``) reflects
    skills added or removed on disk.

    This does NOT invalidate the skills system-prompt cache. Skills are
    called by name via ``/skill-name``, ``skills_list``, or ``skill_view``
    — they don't need to be in the system prompt for the model to use them.
    Keeping the prompt cache intact preserves prefix caching across the
    reload, so a user invoking ``/reload-skills`` pays no cache-reset cost.

    Returns:
        Dict with keys::

            {
              "added":      [{"name": str, "description": str}, ...],
              "removed":    [{"name": str, "description": str}, ...],
              "unchanged":  [skill names present before and after],
              "total":      total skill count after rescan,
              "commands":   total /slash-skill count after rescan,
            }

        ``description`` is the skill's full SKILL.md frontmatter
        ``description:`` field — the same string the system prompt renders
        as ``    - name: description`` for pre-existing skills.
    """
    # Snapshot pre-reload state (name -> description) from the current
    # slash-command cache. Using dicts lets the post-rescan diff carry
    # descriptions for newly-visible or just-removed skills without a
    # second disk walk.
    def _snapshot(cmds: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for slash_key, info in cmds.items():
            bare = slash_key.lstrip("/")
            out[bare] = (info or {}).get("description") or ""
        return out

    before = _snapshot(_skill_commands)

    # Rescan the skills dir. ``scan_skill_commands`` resets
    # ``_skill_commands = {}`` internally and repopulates it.
    new_commands = scan_skill_commands()

    after = _snapshot(new_commands)

    added_names = sorted(set(after) - set(before))
    removed_names = sorted(set(before) - set(after))
    unchanged = sorted(set(after) & set(before))

    added = [{"name": n, "description": after[n]} for n in added_names]
    # For removed skills, use the description we had cached pre-rescan
    # (the skill file is gone so we can't re-read it).
    removed = [{"name": n, "description": before[n]} for n in removed_names]

    return {
        "added": added,
        "removed": removed,
        "unchanged": unchanged,
        "total": len(after),
        "commands": len(new_commands),
    }


def resolve_skill_command_key(command: str) -> Optional[str]:
    """Resolve a user-typed /command to its canonical skill_cmds key.

    Skills are always stored with hyphens — ``scan_skill_commands`` normalizes
    spaces and underscores to hyphens when building the key. Hyphens and
    underscores are treated interchangeably in user input: this matches
    ``_check_unavailable_skill`` and accommodates Telegram bot-command names
    (which disallow hyphens, so ``/claude-code`` is registered as
    ``/claude_code`` and comes back in the underscored form).

    Exact per-skill aliases are also supported via ``metadata.hermes.aliases``
    (or ``command_aliases``) in the skill frontmatter; aliases resolve to the
    canonical command key rather than appearing as separate commands in help.

    Returns the matching canonical ``/slug`` key from ``get_skill_commands()``
    or ``None`` if no match.
    """
    if not command:
        return None
    cmd_key = f"/{command.replace('_', '-')}"
    commands = get_skill_commands()
    if cmd_key in commands:
        return cmd_key
    return _skill_command_aliases.get(cmd_key)


def resolve_bare_skill_invocation(text: str) -> Optional[tuple[str, str]]:
    """Resolve a bare skill-name message into (cmd_key, user_instruction)."""
    stripped = (text or "").strip()
    if not stripped or stripped.startswith("/"):
        return None

    lines = stripped.splitlines()
    skill_token = lines[0].strip()
    if not skill_token or any(ch.isspace() for ch in skill_token):
        return None

    cmd_key = resolve_skill_command_key(skill_token)
    if cmd_key is None:
        return None

    user_instruction = "\n".join(line.rstrip() for line in lines[1:]).strip()
    return cmd_key, user_instruction


def default_skill_runtime_note(
    skill_name: str,
    current_session_id: str | None = None,
) -> str:
    """Return an implicit runtime note for specific skills when useful."""
    normalized = (skill_name or "").strip().lower()
    if normalized in {
        "autonomous-continuation-loop",
        "continuation-loop-controller-slices",
    }:
        note = (
            "A bounded continuation launcher surface exists inside Hermes. "
            "If continuation bootstrap is needed, trigger it yourself with available tools; "
            "do not ask the user to manually run shell commands."
        )
        if current_session_id:
            note += f" Current session id: {current_session_id}. Prefer this session over guessing the most recent CLI session."
        return note
    return ""


def build_skill_invocation_message(
    cmd_key: str,
    user_instruction: str = "",
    task_id: str | None = None,
    runtime_note: str = "",
) -> Optional[str]:
    """Build the user message content for a skill slash command invocation."""
    commands = get_skill_commands()
    skill_info = commands.get(cmd_key)
    if not skill_info:
        return None

    loaded = _load_skill_payload(skill_info["skill_dir"], task_id=task_id)
    if not loaded:
        return f"[Failed to load skill: {skill_info['name']}]"

    loaded_skill, skill_dir, skill_name = loaded

    # Track active usage for Curator lifecycle management (#17782)
    try:
        from tools.skill_usage import bump_use
        bump_use(skill_name)
    except Exception:
        pass  # Non-critical — skill invocation proceeds regardless

    activation_note = (
        f'[IMPORTANT: The user has invoked the "{skill_name}" skill, indicating they want '
        "you to follow its instructions. The full skill content is loaded below.]"
    )
    runtime_note = runtime_note or default_skill_runtime_note(skill_name)
    return _build_skill_message(
        loaded_skill,
        skill_dir,
        activation_note,
        user_instruction=user_instruction,
        runtime_note=runtime_note,
        session_id=task_id,
    )


def build_multi_skill_invocation_message(
    cmd_keys: list[str],
    user_instruction: str = "",
    task_id: str | None = None,
    runtime_note: str = "",
) -> Optional[str]:
    """Build one combined user message that activates multiple skills in order."""
    prompt_parts: list[str] = []
    seen: set[str] = set()

    commands = get_skill_commands()
    for cmd_key in cmd_keys:
        normalized = (cmd_key or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        skill_info = commands.get(normalized)
        if not skill_info:
            return None
        loaded = _load_skill_payload(skill_info["skill_dir"], task_id=task_id)
        if not loaded:
            return f"[Failed to load skill: {skill_info['name']}]"
        loaded_skill, skill_dir, skill_name = loaded
        activation_note = (
            f'[SYSTEM: The user has invoked the "{skill_name}" skill as part of a combined continuation mode. '
            "Follow its instructions together with the other loaded skills below.]"
        )
        prompt_parts.append(
            _build_skill_message(
                loaded_skill,
                skill_dir,
                activation_note,
            )
        )

    if not prompt_parts:
        return None

    if user_instruction:
        prompt_parts.append("")
        prompt_parts.append(
            f"The user has provided the following instruction alongside the combined skill invocation: {user_instruction}"
        )

    if runtime_note:
        prompt_parts.append("")
        prompt_parts.append(f"[Runtime note: {runtime_note}]")

    return "\n\n".join(prompt_parts)


def build_preloaded_skills_prompt(
    skill_identifiers: list[str],
    task_id: str | None = None,
) -> tuple[str, list[str], list[str]]:
    """Load one or more skills for session-wide CLI preloading.

    Returns (prompt_text, loaded_skill_names, missing_identifiers).
    """
    prompt_parts: list[str] = []
    loaded_names: list[str] = []
    missing: list[str] = []

    seen: set[str] = set()
    for raw_identifier in skill_identifiers:
        identifier = (raw_identifier or "").strip()
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)

        loaded = _load_skill_payload(identifier, task_id=task_id)
        if not loaded:
            missing.append(identifier)
            continue

        loaded_skill, skill_dir, skill_name = loaded

        # Track active usage for Curator lifecycle management (#17782)
        try:
            from tools.skill_usage import bump_use
            bump_use(skill_name)
        except Exception:
            pass  # Non-critical

        activation_note = (
            f'[IMPORTANT: The user launched this CLI session with the "{skill_name}" skill '
            "preloaded. Treat its instructions as active guidance for the duration of this "
            "session unless the user overrides them.]"
        )
        prompt_parts.append(
            _build_skill_message(
                loaded_skill,
                skill_dir,
                activation_note,
                session_id=task_id,
            )
        )
        loaded_names.append(skill_name)

    return "\n\n".join(prompt_parts), loaded_names, missing
