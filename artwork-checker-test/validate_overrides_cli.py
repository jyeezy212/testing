#!/usr/bin/env python3
"""
validate_overrides_cli.py — Preflight validation for vision_overrides.json.

Enforces a deterministic, auditable contract between the VISION step and Pass 2.

Checks (in order):
  1. Structural: task_hash, human_token, item IDs confirmed (via core validator)
  2. Audit metadata: generation_mode, generator_version, timestamp, task_hash
  3. Per-item evidence binding:
       source_image  — required, must be in allowed images for that item
       source_image_sha256 — computed from file, must match
       transcription_method — required ("model_retype" or "interactive_cli")
  4. Per-item self-consistency:
       char_count          — must equal len(visual_artwork_value)
       punctuation_signature — must equal computed value
       has_diacritics        — must equal computed value
  5. Per-item nonce: must match prefill nonce for that item
  6. Per-item spotcheck: if prefill has spotcheck_challenge, spotcheck_answer required
  7. Option A: non-exact found=false must supply valid reason_not_found
  8. Anti-reuse: same override VALUES with a different task_hash → reject

On PASS:
  - Writes output/.VISION_DONE
  - Removes output/.VISION_IN_PROGRESS
  - Updates output/.vision_reuse_guard.json

On FAIL:
  - Removes output/.VISION_IN_PROGRESS

Machine tokens (stdout):
  VALIDATE_OVERRIDES_PASS: {"confirmed":K,"found_true":M,"items_total":N}

Machine token (stderr on failure):
  VALIDATE_OVERRIDES_FAIL: {"errors":[...]}

Exit codes:
  0  All checks passed.
  1  Validation failed.
  2  File not found.
"""

import argparse
import hashlib
import json
import string
import sys
import unicodedata
from pathlib import Path

# Windows terminals default to cp1252; force UTF-8 so em-dash and other chars survive
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Mirror of artwork_checker_core constants
_REASON_NOT_FOUND_ALLOWED = frozenset({
    "not_present_on_artwork",
    "illegible",
    "not_in_provided_crops",
    "blocked_or_obscured",
    "language_variant_mismatch",
})
_TRANSCRIPTION_METHODS_ALLOWED = frozenset({
    "model_retype",
    "interactive_cli",
})
_VISION_DONE_FILE = ".VISION_DONE"
_VISION_IN_PROGRESS_FILE = ".VISION_IN_PROGRESS"
_REUSE_GUARD_FILE = ".vision_reuse_guard.json"

# Import from artwork_checker_core (same directory)
try:
    from artwork_checker_core import validate_vision_overrides
except ImportError:
    import importlib.util
    _core = Path(__file__).parent / "artwork_checker_core.py"
    _spec = importlib.util.spec_from_file_location("artwork_checker_core", str(_core))
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    validate_vision_overrides = _mod.validate_vision_overrides


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _compute_nonce(task_hash: str, fid: str) -> str:
    return hashlib.sha256(
        f"{task_hash}:{fid}:nonce_v1".encode()
    ).hexdigest()[:12]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _char_count(value: str) -> int:
    return len(value)


def _punctuation_signature(value: str) -> list:
    return sorted(set(c for c in value if c in string.punctuation))


def _has_diacritics(value: str) -> bool:
    return any(
        unicodedata.category(c).startswith("L") and ord(c) > 127
        for c in value
    )


def _content_hash(overrides: list) -> str:
    """Hash of override values — used for anti-reuse detection."""
    items = sorted(
        (
            o.get("finding_id", ""),
            str(o.get("found")),
            o.get("visual_artwork_value", ""),
            o.get("reason_not_found", ""),
        )
        for o in overrides
    )
    return hashlib.sha256(
        json.dumps(items, sort_keys=True).encode()
    ).hexdigest()[:16]


def _validate_spotcheck(answer: str, challenge_type: str, value: str) -> bool:
    """Check that spotcheck_answer is self-consistent with visual_artwork_value."""
    if not value:
        return True  # found=false — spotcheck not applicable
    if challenge_type == "first_3_chars":
        return answer == value[:3]
    elif challenge_type == "char_count":
        return str(answer).strip() == str(len(value))
    elif challenge_type == "last_3_chars":
        return answer == value[-3:]
    elif challenge_type == "first_word":
        words = value.split()
        return answer == (words[0] if words else "")
    elif challenge_type == "contains_digit":
        expected = any(c.isdigit() for c in value)
        return str(answer).strip().lower() in (
            str(expected).lower(), "true" if expected else "false"
        )
    return True  # unknown type — pass


# ---------------------------------------------------------------------------
# Validation sub-checks
# ---------------------------------------------------------------------------

def _load_enriched_prefill(output_dir: Path) -> dict:
    """
    Load the enriched prefill written by run_vision_step.py.
    Returns empty dict if not found — checks downstream handle absence gracefully.
    """
    p = output_dir / "gpt_vision" / "vision_overrides.prefill.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _check_audit_metadata(audit: dict, expected_task_hash: str) -> list:
    issues = []
    if not (audit.get("generation_mode") or "").strip():
        issues.append(
            "vision_audit.generation_mode is missing. "
            "Required: 'interactive_ai' or 'interactive_cli'."
        )
    if not (audit.get("generator_version") or "").strip():
        issues.append("vision_audit.generator_version is missing.")
    if not (audit.get("timestamp") or "").strip():
        issues.append("vision_audit.timestamp is missing (ISO8601 required).")
    provided_hash = (audit.get("task_hash") or "").strip()
    if provided_hash and expected_task_hash and provided_hash != expected_task_hash:
        issues.append(
            f"vision_audit.task_hash mismatch: "
            f"expected '{expected_task_hash}', got '{provided_hash}'."
        )
    return issues


def _check_anti_reuse(
    overrides: list, output_dir: Path, task_hash: str
) -> tuple:
    """Detect reuse of identical override values across different runs. Returns (errors, chash)."""
    issues = []
    chash = _content_hash(overrides)
    guard_path = output_dir / _REUSE_GUARD_FILE
    guard = {}
    if guard_path.exists():
        try:
            guard = json.loads(guard_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Build reverse map: content_hash → list of task_hashes that used it
    reverse = {}
    for th, ch in guard.items():
        reverse.setdefault(ch, []).append(th)

    prior_uses = [th for th in reverse.get(chash, []) if th != task_hash]
    if prior_uses:
        issues.append(
            "Anti-reuse: identical override values were previously used for a different run "
            f"(task_hash={prior_uses[0][:8]}...). This suggests static/hardcoded mappings. "
            "Complete a fresh visual read of the images for this run."
        )
    return issues, chash


def _check_item_states(raw: dict, output_dir: Path, enriched_prefill: dict) -> list:
    """
    Full per-item validation:
      - Basic consistency (found/value/confirmed)
      - Evidence binding (source_image, SHA256)
      - Self-consistency fields (char_count, punctuation_signature, has_diacritics)
      - Nonce match
      - Spotcheck answer
      - Option A (reason_not_found)
    """
    issues = []

    # Load item match_types for Option A
    item_match_types = {}
    tasks_path = output_dir / "gpt_vision" / "vision_tasks.json"
    if tasks_path.exists():
        try:
            tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))
            item_match_types = {
                it["id"]: it.get("script_match_type", "")
                for it in tasks_data.get("items", [])
            }
        except Exception:
            pass

    pf_map = {o["finding_id"]: o for o in enriched_prefill.get("overrides", [])}
    has_enriched = bool(pf_map)

    for o in raw.get("overrides", []):
        fid = o.get("finding_id", "?")
        found = o.get("found", False)
        value = (o.get("visual_artwork_value") or "").strip()
        confirmed = o.get("confirmed", False)
        pf = pf_map.get(fid, {})

        # ── Basic ────────────────────────────────────────────────────────
        if found and not value:
            issues.append(f"[{fid}] found=true but visual_artwork_value is empty.")
        if not found and value:
            issues.append(
                f"[{fid}] found=false but visual_artwork_value is set ('{value[:40]}')."
            )
        if confirmed is not True:
            issues.append(f"[{fid}] confirmed is not true (got: {confirmed!r}).")

        # ── Evidence binding: source_image ───────────────────────────────
        source_image = (o.get("source_image") or "").strip()
        if not source_image:
            issues.append(f"[{fid}] source_image is missing (required).")
        else:
            # Must be in allowed images from enriched prefill
            if has_enriched and pf:
                allowed = {pf.get("recommended_source_image", "")}
                allowed.update(pf.get("alternate_images", []))
                allowed.discard("")
                if allowed and source_image not in allowed:
                    issues.append(
                        f"[{fid}] source_image '{source_image}' not in allowed images. "
                        f"Allowed: {sorted(allowed)}"
                    )

            # Must exist on disk + SHA256 match
            abs_src = Path(source_image)
            if not abs_src.is_absolute():
                abs_src = output_dir / source_image
            if not abs_src.exists():
                issues.append(
                    f"[{fid}] source_image does not exist on disk: {source_image}"
                )
            else:
                provided_sha = (o.get("source_image_sha256") or "").strip()
                if not provided_sha:
                    issues.append(
                        f"[{fid}] source_image_sha256 is missing. "
                        "Use build_overrides_from_ai_response.py to fill it in."
                    )
                else:
                    try:
                        actual_sha = _sha256_file(abs_src)
                        if actual_sha != provided_sha:
                            issues.append(
                                f"[{fid}] source_image_sha256 mismatch for '{source_image}'.\n"
                                f"  Provided : {provided_sha}\n"
                                f"  Actual   : {actual_sha}"
                            )
                    except Exception as e:
                        issues.append(
                            f"[{fid}] Cannot read '{source_image}' for SHA256: {e}"
                        )

        # ── transcription_method ─────────────────────────────────────────
        tm = (o.get("transcription_method") or "").strip()
        if not tm:
            issues.append(
                f"[{fid}] transcription_method is missing. "
                f"Allowed: {sorted(_TRANSCRIPTION_METHODS_ALLOWED)}"
            )
        elif tm not in _TRANSCRIPTION_METHODS_ALLOWED:
            issues.append(
                f"[{fid}] transcription_method '{tm}' not allowed. "
                f"Allowed: {sorted(_TRANSCRIPTION_METHODS_ALLOWED)}"
            )

        # ── Self-consistency (only when found=true) ──────────────────────
        if found and value:
            exp_cc = _char_count(value)
            prov_cc = o.get("char_count")
            if prov_cc is None:
                issues.append(f"[{fid}] char_count is missing.")
            elif int(prov_cc) != exp_cc:
                issues.append(
                    f"[{fid}] char_count mismatch: provided {prov_cc}, "
                    f"computed {exp_cc}."
                )

            exp_ps = _punctuation_signature(value)
            prov_ps = o.get("punctuation_signature")
            if prov_ps is None:
                issues.append(f"[{fid}] punctuation_signature is missing.")
            elif list(prov_ps) != exp_ps:
                issues.append(
                    f"[{fid}] punctuation_signature mismatch: "
                    f"provided {prov_ps}, computed {exp_ps}."
                )

            exp_hd = _has_diacritics(value)
            prov_hd = o.get("has_diacritics")
            if prov_hd is None:
                issues.append(f"[{fid}] has_diacritics is missing.")
            elif bool(prov_hd) != exp_hd:
                issues.append(
                    f"[{fid}] has_diacritics mismatch: provided {prov_hd}, computed {exp_hd}."
                )

        # ── Nonce ────────────────────────────────────────────────────────
        if has_enriched and pf:
            expected_nonce = pf.get("nonce", "")
            provided_nonce = (o.get("nonce") or "").strip()
            if not provided_nonce:
                issues.append(
                    f"[{fid}] nonce is missing. Expected: '{expected_nonce}'"
                )
            elif provided_nonce != expected_nonce:
                issues.append(
                    f"[{fid}] nonce mismatch: "
                    f"expected '{expected_nonce}', got '{provided_nonce}'."
                )

        # ── Spotcheck ────────────────────────────────────────────────────
        if has_enriched and pf and pf.get("spotcheck_challenge"):
            challenge = pf["spotcheck_challenge"]
            sc_answer = (o.get("spotcheck_answer") or "").strip()
            if not sc_answer:
                issues.append(
                    f"[{fid}] spotcheck_answer required "
                    f"({challenge['type']}: {challenge['instruction']})"
                )
            elif found and value:
                if not _validate_spotcheck(sc_answer, challenge["type"], value):
                    issues.append(
                        f"[{fid}] spotcheck_answer '{sc_answer}' inconsistent with "
                        f"value '{value[:30]}' (challenge: {challenge['type']})."
                    )

        # ── Option A: reason_not_found ───────────────────────────────────
        match_type = item_match_types.get(fid, "")
        if match_type != "exact" and not found:
            reason = (o.get("reason_not_found") or "").strip()
            if not reason:
                issues.append(
                    f"[{fid}] found=false but reason_not_found is missing. "
                    f"Allowed: {sorted(_REASON_NOT_FOUND_ALLOWED)}"
                )
            elif reason not in _REASON_NOT_FOUND_ALLOWED:
                issues.append(
                    f"[{fid}] reason_not_found '{reason}' not allowed. "
                    f"Allowed: {sorted(_REASON_NOT_FOUND_ALLOWED)}"
                )

    return issues


# ---------------------------------------------------------------------------
# Lock file management
# ---------------------------------------------------------------------------

def _write_vision_done(output_dir: Path, task_hash: str) -> None:
    import datetime as _dt
    p = output_dir / _VISION_DONE_FILE
    try:
        p.write_text(
            json.dumps({
                "task_hash": task_hash,
                "validated": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            }),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"WARNING: Could not write {_VISION_DONE_FILE}: {e}", file=sys.stderr)


def _clear_vision_in_progress(output_dir: Path) -> None:
    p = output_dir / _VISION_IN_PROGRESS_FILE
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass


def _update_reuse_guard(output_dir: Path, task_hash: str, chash: str) -> None:
    guard_path = output_dir / _REUSE_GUARD_FILE
    guard = {}
    if guard_path.exists():
        try:
            guard = json.loads(guard_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    guard[task_hash] = chash
    try:
        guard_path.write_text(json.dumps(guard, indent=2), encoding="utf-8")
    except Exception:
        pass


def _fail(errors: list, exit_code: int = 1, output_dir: "Path | None" = None) -> None:
    if output_dir is not None:
        _clear_vision_in_progress(output_dir)
    fail_data = {"errors": [e.strip() for e in errors]}
    print(
        f"VALIDATE_OVERRIDES_FAIL: {json.dumps(fail_data, ensure_ascii=False, sort_keys=True)}",
        file=sys.stderr,
        flush=True,
    )
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preflight validation for vision_overrides.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=Path("./output"),
        help="Output directory used in Pass 1 (default: ./output)",
    )
    parser.add_argument(
        "--overrides", type=Path, default=None,
        help="Path to vision_overrides.json (default: <output>/vision_overrides.json)",
    )
    args = parser.parse_args()

    output_dir = args.output
    overrides_path = args.overrides or (output_dir / "vision_overrides.json")

    sep = "=" * 60
    print(f"\n{sep}")
    print("VISION OVERRIDES — PREFLIGHT VALIDATION")
    print(f"{sep}")
    print(f"  Output dir : {output_dir}")
    print(f"  Overrides  : {overrides_path}")
    print()

    # ── File existence ────────────────────────────────────────────────────
    if not overrides_path.exists():
        print(f"ERROR: overrides file not found: {overrides_path}", file=sys.stderr)
        _fail(
            [f"overrides file not found: {overrides_path}"],
            exit_code=2,
            output_dir=output_dir,
        )

    tasks_path = output_dir / "gpt_vision" / "vision_tasks.json"
    if not tasks_path.exists():
        print(f"ERROR: vision_tasks.json not found: {tasks_path}", file=sys.stderr)
        _fail(
            [f"vision_tasks.json not found: {tasks_path} — run Pass 1 first."],
            exit_code=2,
            output_dir=output_dir,
        )

    # ── Parse ─────────────────────────────────────────────────────────────
    try:
        raw = json.loads(overrides_path.read_text(encoding="utf-8"))
    except Exception as e:
        _fail([f"Cannot parse overrides file: {e}"], output_dir=output_dir)

    audit = raw.get("vision_audit", {})
    task_hash_from_tasks = ""
    try:
        task_hash_from_tasks = json.loads(
            tasks_path.read_text(encoding="utf-8")
        ).get("task_hash", "")
    except Exception:
        pass

    enriched_prefill = _load_enriched_prefill(output_dir)
    all_errors = []

    # ── 1. Core structural validation ─────────────────────────────────────
    try:
        validate_vision_overrides(
            output_dir=str(output_dir),
            vision_overrides_path=str(overrides_path),
            check_human_token=True,
        )
    except (ValueError, FileNotFoundError) as e:
        all_errors.append(f"Structural validation: {e}")

    # ── 2. Audit metadata ─────────────────────────────────────────────────
    all_errors.extend(_check_audit_metadata(audit, task_hash_from_tasks))

    # ── 3–7. Per-item checks ──────────────────────────────────────────────
    all_errors.extend(_check_item_states(raw, output_dir, enriched_prefill))

    # ── 8. Anti-reuse ─────────────────────────────────────────────────────
    provided_task_hash = (audit.get("task_hash") or "").strip()
    effective_task_hash = provided_task_hash or task_hash_from_tasks
    reuse_errors, chash = _check_anti_reuse(
        raw.get("overrides", []), output_dir, effective_task_hash
    )
    all_errors.extend(reuse_errors)

    # ── Fail? ─────────────────────────────────────────────────────────────
    if all_errors:
        print(f"FAIL — {len(all_errors)} error(s):", file=sys.stderr)
        for err in all_errors:
            print(f"  {err}", file=sys.stderr)
        print(f"\n{sep}", file=sys.stderr)
        _fail(all_errors, exit_code=1, output_dir=output_dir)

    # ── All good ──────────────────────────────────────────────────────────
    overrides_list = raw.get("overrides", [])
    n = len(overrides_list)
    confirmed = sum(1 for o in overrides_list if o.get("confirmed") is True)
    found_true = sum(1 for o in overrides_list if o.get("found") is True)

    print(f"  Items total  : {n}")
    print(f"  confirmed    : {confirmed}/{n}")
    print(f"  found=true   : {found_true}/{n}")
    print(f"\n{sep}\n")

    _write_vision_done(output_dir, effective_task_hash)
    _clear_vision_in_progress(output_dir)
    _update_reuse_guard(output_dir, effective_task_hash, chash)

    token_data = {"confirmed": confirmed, "found_true": found_true, "items_total": n}
    print(
        f"VALIDATE_OVERRIDES_PASS: {json.dumps(token_data, ensure_ascii=False, sort_keys=True)}",
        flush=True,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
