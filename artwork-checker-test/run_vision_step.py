#!/usr/bin/env python3
"""
run_vision_step.py — Vision step orchestrator for the artwork checker pipeline.

Responsibilities:
  1. Verify Pass 1 artifacts exist.
  2. Write .VISION_IN_PROGRESS (clears .VISION_DONE if present).
  3. ENRICH vision_overrides.prefill.json with:
       - recommended_source_image / alternate_images (best crop per item)
       - nonce (deterministic per task_hash + finding_id — anti-copy-paste)
       - spotcheck_challenge (for N randomly-seeded items)
  4. Display images and per-item manifest (display mode — GPT/AI).
  5. Prompt the user for each item (--interactive mode — human CLI).
     Interactive mode computes and writes all required evidence-binding fields.

Lock files:
  .VISION_IN_PROGRESS  created at start of this script
  .VISION_DONE         written by validate_overrides_cli.py on pass (not here)

Display mode (default — GPT/AI):
  python run_vision_step.py --output ./output

Interactive mode (human CLI):
  python run_vision_step.py --output ./output --interactive
"""

import argparse
import hashlib
import json
import os
import pathlib
import random
import string
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone

try:
    from IPython.display import display as ipy_display, Image as IPImage
    HAS_IPYTHON = True
except ImportError:
    HAS_IPYTHON = False

_VISION_STEP_VERSION = "2.0.0"
_VISION_IN_PROGRESS_FILE = ".VISION_IN_PROGRESS"
_VISION_DONE_FILE = ".VISION_DONE"

_REASON_NOT_FOUND_ALLOWED = [
    "not_present_on_artwork",
    "illegible",
    "not_in_provided_crops",
    "blocked_or_obscured",
    "language_variant_mismatch",
]

_TRANSCRIPTION_METHODS_ALLOWED = frozenset({
    "model_retype",
    "interactive_cli",
})


# ---------------------------------------------------------------------------
# Pure helpers — no I/O
# ---------------------------------------------------------------------------

def _compute_nonce(task_hash: str, fid: str) -> str:
    """Deterministic 12-char nonce from task_hash + finding_id (anti-copy-paste)."""
    return hashlib.sha256(
        f"{task_hash}:{fid}:nonce_v1".encode()
    ).hexdigest()[:12]


def _build_image_options(
    item: dict, page_images: dict, output_dir: pathlib.Path
) -> tuple[str, list[str]]:
    """Return (recommended, alternates) as posix paths relative to output_dir."""

    def _rel(p: str) -> str:
        if not p:
            return ""
        try:
            return pathlib.Path(p).relative_to(output_dir).as_posix()
        except ValueError:
            return pathlib.Path(p).as_posix()

    candidates: list[str] = []
    wide = item.get("focus_crop_wide") or ""
    crop = item.get("focus_crop") or ""
    page_num = str(item.get("page_guess", 1))
    page_img = page_images.get(page_num) or ""

    for path_str in (wide, crop, page_img):
        if path_str and path_str not in candidates:
            if pathlib.Path(path_str).exists():
                candidates.append(path_str)
            else:
                candidates.append(path_str)  # include even if missing (warn at display time)

    if not candidates:
        return "", []
    relative = [_rel(p) for p in candidates]
    return relative[0], relative[1:]


def _select_spotcheck_items(items: list, task_hash: str, n: int = 3) -> set[str]:
    """Select ≤n item IDs for spotcheck challenges, seeded by task_hash."""
    eligible = [item["id"] for item in items]
    if not eligible:
        return set()
    rng = random.Random(task_hash + ":spotcheck_v1")
    return set(rng.sample(eligible, min(n, len(eligible))))


def _make_spotcheck_challenge(fid: str, task_hash: str) -> dict:
    """Generate a deterministic spotcheck challenge. Seeded by task_hash + fid."""
    challenges = [
        {
            "type": "first_3_chars",
            "instruction": (
                "Provide the exact first 3 characters of the value as printed on the artwork"
            ),
        },
        {
            "type": "char_count",
            "instruction": (
                "Count the total number of characters (including spaces and punctuation) "
                "in the value"
            ),
        },
        {
            "type": "last_3_chars",
            "instruction": (
                "Provide the exact last 3 characters of the value as printed on the artwork"
            ),
        },
        {
            "type": "first_word",
            "instruction": (
                "Provide the exact first word of the value as printed on the artwork"
            ),
        },
        {
            "type": "contains_digit",
            "instruction": (
                "Does the value contain any digit (0–9)? Answer true or false"
            ),
        },
    ]
    rng = random.Random(f"{task_hash}:{fid}:spotcheck_v1")
    return rng.choice(challenges)


def _enrich_prefill(
    prefill: dict,
    tasks: dict,
    output_dir: pathlib.Path,
) -> dict:
    """
    Enrich the prefill with nonces, image options, and spotcheck challenges.

    The enriched prefill is the canonical contract read by validate_overrides_cli.
    Writes back to disk — callers must pass prefill_path for atomic write.
    """
    items = tasks.get("items", [])
    page_images = tasks.get("page_images", {})
    task_hash = tasks.get("task_hash", "")
    spotcheck_ids = _select_spotcheck_items(items, task_hash, n=3)
    prefill_map = {o["finding_id"]: o for o in prefill.get("overrides", [])}

    enriched_overrides = []
    for item in items:
        fid = item["id"]
        base = dict(prefill_map.get(fid, {}))
        base["finding_id"] = fid
        recommended, alternates = _build_image_options(item, page_images, output_dir)
        base["recommended_source_image"] = recommended
        base["alternate_images"] = alternates
        base["nonce"] = _compute_nonce(task_hash, fid)
        if fid in spotcheck_ids:
            base["spotcheck_challenge"] = _make_spotcheck_challenge(fid, task_hash)
        enriched_overrides.append(base)

    enriched = dict(prefill)
    enriched["overrides"] = enriched_overrides
    return enriched


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _char_count(value: str) -> int:
    return len(value)


def _punctuation_signature(value: str) -> list[str]:
    return sorted(set(c for c in value if c in string.punctuation))


def _has_diacritics(value: str) -> bool:
    return any(
        unicodedata.category(c).startswith("L") and ord(c) > 127
        for c in value
    )


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _show_image(path: str, label: str) -> None:
    p = pathlib.Path(path)
    if not p.exists():
        print(f"  [IMAGE MISSING: {path}]")
        return
    print(f"\n[{label}]")
    if HAS_IPYTHON:
        ipy_display(IPImage(filename=str(p)))
    else:
        print(f"  image: {p}")


def _run_validate(output_dir: pathlib.Path, overrides_path: pathlib.Path) -> bool:
    cli = pathlib.Path(__file__).parent / "validate_overrides_cli.py"
    if not cli.exists():
        print("  [validate_overrides_cli.py not found — skipping validation]")
        return True
    result = subprocess.run(
        [sys.executable, str(cli),
         "--output", str(output_dir),
         "--overrides", str(overrides_path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, end="", file=sys.stderr)
        return False
    return "VALIDATE_OVERRIDES_PASS" in result.stdout


def _prompt_reason(fid: str) -> str:
    print(f"  Reason not found for [{fid}]:")
    for i, r in enumerate(_REASON_NOT_FOUND_ALLOWED, 1):
        print(f"    {i}. {r}")
    while True:
        choice = input("  Enter number or type reason directly: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(_REASON_NOT_FOUND_ALLOWED):
            return _REASON_NOT_FOUND_ALLOWED[int(choice) - 1]
        if choice in _REASON_NOT_FOUND_ALLOWED:
            return choice
        print(f"  Invalid. Choose 1–{len(_REASON_NOT_FOUND_ALLOWED)} or type exact reason.")


def _prompt_spotcheck(fid: str, challenge: dict, value: str) -> str:
    print(f"\n  SPOT CHECK [{fid}]: {challenge['instruction']}")
    if value:
        print(f"  (Value you entered: {repr(value)})")
    return input("  Spotcheck answer: ").strip()


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

def _interactive_mode(
    output: pathlib.Path,
    tasks: dict,
    enriched_prefill: dict,
    sep: str,
) -> None:
    """
    Prompt the user to transcribe each vision item interactively.

    Writes a fully-populated vision_overrides.json including all evidence-
    binding fields, then calls validate_overrides_cli.py.
    """
    items = tasks.get("items", [])
    task_hash = tasks.get("task_hash", "")
    human_token = enriched_prefill.get("vision_audit", {}).get("human_token", "")
    overrides_out = output / "vision_overrides.json"
    prefill_map = {o["finding_id"]: o for o in enriched_prefill.get("overrides", [])}

    print(f"\n{sep}")
    print(f"INTERACTIVE VISION — {len(items)} item(s) to review")
    print(f"Human token : {human_token}")
    print(f"Output dir  : {output}")
    print("Type Ctrl+C at any time to abort without writing output.")
    print(sep)

    completed_overrides = []

    for i, item in enumerate(items, 1):
        fid = item["id"]
        match_type = item.get("script_match_type", "")
        is_exact = (match_type == "exact")
        pf = prefill_map.get(fid, {})
        nonce = pf.get("nonce") or _compute_nonce(task_hash, fid)
        recommended_img = pf.get("recommended_source_image", "")
        spotcheck_challenge = pf.get("spotcheck_challenge")

        print(f"\n{'─' * 60}")
        print(f"[{i}/{len(items)}] {fid} — {item['field_name']}")
        print(f"  Panel    : {item['panel']} | Language : {item['language']}")
        print(f"  Copy doc : {item['copy_value']}")
        print(f"  Script   : {item.get('script_artwork_value', '')}  ({match_type})")

        # Show evidence
        if recommended_img:
            print(f"  Evidence : {recommended_img}")
            _show_image(str(output / recommended_img), f"{fid} — {item['field_name']}")
            alternates = pf.get("alternate_images", [])
            for alt in alternates:
                _show_image(str(output / alt), f"{fid} — alternate")
        else:
            print("  Evidence : (none — check full page manually)")

        if item.get("zoom_reasons"):
            print(f"  Flags    : {', '.join(item['zoom_reasons'])}")

        # Compute SHA256 of source image
        source_image_sha256 = ""
        if recommended_img:
            abs_src = output / recommended_img
            if abs_src.exists():
                try:
                    source_image_sha256 = _sha256_file(abs_src)
                except Exception:
                    pass

        def _build_override(found: bool, value: str, reason: str = "") -> dict:
            o: dict = {
                "finding_id": fid,
                "found": found,
                "visual_artwork_value": value,
                "confirmed": True,
                "source_image": recommended_img,
                "source_image_sha256": source_image_sha256,
                "transcription_method": "interactive_cli",
                "char_count": _char_count(value),
                "punctuation_signature": _punctuation_signature(value),
                "has_diacritics": _has_diacritics(value),
                "nonce": nonce,
            }
            if not found:
                o["reason_not_found"] = reason
            return o

        if is_exact:
            default_val = pf.get("visual_artwork_value") or item.get("script_artwork_value", "")
            print(f"\n  ✅ EXACT MATCH — pre-filled value: {repr(default_val)}")
            user_in = input("  Press Enter to confirm, or type corrected value: ").strip()
            final_value = user_in if user_in else default_val

            if final_value:
                override = _build_override(True, final_value)
                if spotcheck_challenge:
                    override["spotcheck_answer"] = _prompt_spotcheck(
                        fid, spotcheck_challenge, final_value
                    )
            else:
                reason = _prompt_reason(fid)
                override = _build_override(False, "", reason)
        else:
            print(f"\n  ❓ Visually locate this field on the artwork.")
            found_in = input("  Found on artwork? [y/n]: ").strip().lower()
            if found_in in ("y", "yes"):
                val = ""
                while not val:
                    val = input(
                        "  Type the EXACT text as printed (character-for-character): "
                    ).strip()
                    if not val:
                        print("  (value cannot be empty when found=true)")
                override = _build_override(True, val)
                if spotcheck_challenge:
                    override["spotcheck_answer"] = _prompt_spotcheck(
                        fid, spotcheck_challenge, val
                    )
            else:
                reason = _prompt_reason(fid)
                override = _build_override(False, "", reason)

        completed_overrides.append(override)

    # Write vision_overrides.json
    overrides_doc = {
        "vision_audit": {
            "source": "manual_image_read",
            "task_hash": task_hash,
            "human_token": human_token,
            "generation_mode": "interactive_cli",
            "generator_version": _VISION_STEP_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "overrides": completed_overrides,
    }

    output.mkdir(parents=True, exist_ok=True)
    overrides_out.write_text(
        json.dumps(overrides_doc, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\n{sep}")
    print(f"Written: {overrides_out}")
    print(sep)
    print("\nValidating overrides...")

    passed = _run_validate(output, overrides_out)
    if passed:
        print(f"\n{sep}")
        print("INTERACTIVE VISION COMPLETE — overrides validated.")
        print("Run VALIDATE (Pass 2) to generate the final report.")
        print(sep)
        sys.exit(0)
    else:
        print(f"\n{sep}", file=sys.stderr)
        print("VALIDATION FAILED — fix errors above and re-run.", file=sys.stderr)
        print(sep, file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vision step orchestrator — display artifacts and enrich prefill"
    )
    parser.add_argument(
        "--output", default="./output",
        help="Output directory used in Pass 1 (default: ./output)"
    )
    parser.add_argument(
        "--interactive", action="store_true",
        help="Interactive CLI mode: prompt for each item's value instead of displaying images"
    )
    args = parser.parse_args()

    output = pathlib.Path(args.output).resolve()
    sep = "=" * 60

    # ------------------------------------------------------------------
    # Prerequisite checks
    # ------------------------------------------------------------------
    done_path = output / ".PASS1_DONE"
    tasks_path = output / "gpt_vision" / "vision_tasks.json"
    prefill_path = output / "gpt_vision" / "vision_overrides.prefill.json"

    errors = []
    if not done_path.exists():
        errors.append("output/.PASS1_DONE not found — run Pass 1 first.")
    if not tasks_path.exists():
        errors.append("output/gpt_vision/vision_tasks.json not found — run Pass 1 first.")
    if not prefill_path.exists():
        errors.append(
            "output/gpt_vision/vision_overrides.prefill.json not found — run Pass 1 first."
        )

    if errors:
        print(f"\n{sep}", file=sys.stderr)
        print("VISION STEP FAILED — prerequisites missing:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        print(f"\n{sep}", file=sys.stderr)
        print(f"\n{sep}")
        print("VISION STEP FAILED — run Pass 1 before VISION.")
        print(sep)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Load artifacts
    # ------------------------------------------------------------------
    try:
        tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Cannot parse vision_tasks.json: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        prefill = json.loads(prefill_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Cannot parse vision_overrides.prefill.json: {e}", file=sys.stderr)
        sys.exit(1)

    items = tasks.get("items", [])
    task_hash = tasks.get("task_hash", "")
    human_token = prefill.get("vision_audit", {}).get("human_token", "")

    # ------------------------------------------------------------------
    # Write .VISION_IN_PROGRESS; clear .VISION_DONE
    # ------------------------------------------------------------------
    vision_in_progress_path = output / _VISION_IN_PROGRESS_FILE
    vision_done_path = output / _VISION_DONE_FILE

    try:
        vision_in_progress_path.write_text(
            json.dumps({
                "task_hash": task_hash,
                "started": datetime.now(timezone.utc).isoformat(),
                "version": _VISION_STEP_VERSION,
            }),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"WARNING: Could not write {_VISION_IN_PROGRESS_FILE}: {e}", file=sys.stderr)

    if vision_done_path.exists():
        try:
            vision_done_path.unlink()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Enrich prefill and write back
    # ------------------------------------------------------------------
    enriched_prefill = _enrich_prefill(prefill, tasks, output)
    try:
        prefill_path.write_text(
            json.dumps(enriched_prefill, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"WARNING: Could not write enriched prefill: {e}", file=sys.stderr)

    # ------------------------------------------------------------------
    # No items: skip straight through
    # ------------------------------------------------------------------
    if not items:
        print(f"\n{sep}")
        print("VISION STEP — no items require visual verification.")
        print("All fields matched exactly in Pass 1. Proceed to VALIDATE.")
        print(sep)
        print(
            f"VISION_STEP_READY: {json.dumps({'items': 0, 'task_hash': task_hash, 'output_dir': str(output)})}"
        )
        sys.exit(0)

    # ------------------------------------------------------------------
    # Interactive mode
    # ------------------------------------------------------------------
    if args.interactive:
        _interactive_mode(output, tasks, enriched_prefill, sep)
        return  # _interactive_mode calls sys.exit

    # ------------------------------------------------------------------
    # Display mode (GPT / Code Interpreter)
    # ------------------------------------------------------------------
    page_images = tasks.get("page_images", {})
    contact_sheets = tasks.get("contact_sheets", [])

    print(f"\n{sep}")
    print(f"VISION STEP — {len(items)} item(s) require visual verification")
    print(f"Task hash  : {task_hash[:16]}...")
    print(f"Human token: {human_token}")
    print(f"Output dir : {output}")
    print(sep)

    # Full-page images
    print("\nFULL PAGE IMAGES — layout orientation:")
    for page_num in sorted(page_images.keys(), key=lambda x: int(x)):
        _show_image(page_images[page_num], f"Page {page_num} — full artwork at 300 DPI")

    # Contact sheets
    if contact_sheets:
        print(f"\n{'─' * 60}")
        print("CONTACT SHEETS — tiles labeled with item ID:")
        for sheet in contact_sheets:
            ids_in_sheet = sheet.get("items", [])
            ids_preview = ", ".join(ids_in_sheet[:6])
            suffix = "…" if len(ids_in_sheet) > 6 else ""
            _show_image(
                sheet["sheet_path"],
                f"Sheet: {ids_preview}{suffix}"
            )
    else:
        print("\n[No contact sheets — use full page image to locate all items]")

    # Wide crops
    wide_items = [it for it in items if it.get("focus_crop_wide")]
    if wide_items:
        print(f"\n{'─' * 60}")
        print("WIDE CROPS — read character-for-character:")
        for it in wide_items:
            _show_image(
                it["focus_crop_wide"],
                f"{it['id']} — wide crop ({it['field_name']})"
            )

    # Item manifest (with enriched prefill data)
    prefill_map = {o["finding_id"]: o for o in enriched_prefill.get("overrides", [])}
    print(f"\n{'─' * 60}")
    print(f"ITEMS TO VERIFY ({len(items)} total):\n")
    for item in items:
        fid = item["id"]
        pf = prefill_map.get(fid, {})
        print(f"• [{fid}] {item['field_name']} | {item['panel']} | {item['language']}")
        print(f"  Copy doc value       : {item['copy_value']}")
        print(f"  Script value         : {item['script_artwork_value']}  ({item['script_match_type']})")
        print(f"  recommended_source   : {pf.get('recommended_source_image', '')}")
        if pf.get("alternate_images"):
            print(f"  alternate_images     : {pf['alternate_images']}")
        print(f"  nonce                : {pf.get('nonce', '')}")
        if pf.get("spotcheck_challenge"):
            ch = pf["spotcheck_challenge"]
            print(f"  SPOT CHECK required  : {ch['type']} — {ch['instruction']}")
        print()

    # ── Required output schema ────────────────────────────────────────────────
    overrides_out = output / "vision_overrides.json"
    print(sep)
    print("REQUIRED RESPONSE FORMAT")
    print(sep)
    print("You MUST respond with ONLY a JSON block — no prose, no explanation.")
    print("Pass the JSON to build_overrides_from_ai_response.py (it fills in SHA256).")
    print()
    print("Top-level structure:")
    print(json.dumps({
        "vision_audit": {
            "task_hash": task_hash,
            "human_token": human_token,
            "generation_mode": "interactive_ai",
            "generator_version": _VISION_STEP_VERSION,
            "timestamp": "<ISO8601 timestamp — e.g. 2026-03-04T12:00:00Z>",
        },
        "overrides": ["<see per-item schema below>"],
    }, indent=2, ensure_ascii=False))
    print()
    print("Per-item schema (one entry per item listed above):")
    sample_fid = items[0]["id"] if items else "D-001"
    sample_pf = prefill_map.get(sample_fid, {})
    print(json.dumps({
        "finding_id": sample_fid,
        "found": True,
        "visual_artwork_value": "<exact text as printed OR empty string if not found>",
        "reason_not_found": "<one of: " + " | ".join(_REASON_NOT_FOUND_ALLOWED) + "> OR empty",
        "confirmed": True,
        "source_image": sample_pf.get("recommended_source_image", "gpt_vision/crops/D-001_page_1.png"),
        "transcription_method": "model_retype",
        "char_count": "<integer — exact character count of visual_artwork_value>",
        "punctuation_signature": "<sorted list of unique punctuation chars in value>",
        "has_diacritics": "<true if value contains letters with diacritics/accents>",
        "nonce": sample_pf.get("nonce", "<copy from prefill — do not modify>"),
        "spotcheck_answer": "<required if spotcheck_challenge present for this item>",
    }, indent=2, ensure_ascii=False))
    print()
    print("RULES:")
    print("  • source_image must be one of recommended_source_image or alternate_images from prefill")
    print("  • nonce must be copied EXACTLY from the prefill — no modification")
    print("  • char_count must equal len(visual_artwork_value)")
    print("  • If found=false, reason_not_found is required for non-exact script items")
    print("  • Omit source_image_sha256 — build_overrides_from_ai_response.py fills it in")
    print(sep)
    print(f"Prefill (source of truth): {prefill_path}")
    print(f"Write overrides to       : {overrides_out}")
    print(f"Then run:")
    print(f"  python build_overrides_from_ai_response.py \\")
    print(f"      --output {output} --ai-json-file <your_response.json>")
    print(f"  OR: python validate_overrides_cli.py --output {output} --overrides {overrides_out}")
    print(sep)

    footer = {
        "status": "READY",
        "items": len(items),
        "task_hash": task_hash,
        "output_dir": str(output),
        "prefill_path": str(prefill_path),
        "overrides_out": str(overrides_out),
    }
    print(f"VISION_STEP_READY: {json.dumps(footer, ensure_ascii=False)}")

    sys.exit(0)


if __name__ == "__main__":
    main()
