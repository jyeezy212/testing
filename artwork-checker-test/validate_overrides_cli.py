#!/usr/bin/env python3
"""
validate_overrides_cli.py — Preflight validation for vision_overrides.json.

Run this BEFORE pass2 to catch structural errors early and get clear,
actionable error messages without wasting a full Pass 2 execution.

Usage:
  python validate_overrides_cli.py \\
      --output ./output \\
      --overrides ./output/vision_overrides.json

Exit codes:
  0  All checks passed — safe to run Pass 2.
  1  Validation failed — see error output.
  2  File not found — missing overrides or vision_tasks.json.

Machine tokens (stdout):
  VALIDATE_OVERRIDES_PASS: {"confirmed":K,"found_true":M,"items_total":N}
  VALIDATE_OVERRIDES_FAIL: {"errors":[...]}   (written to stderr on failure)
"""

import argparse
import json
import sys
from pathlib import Path

# Import from artwork_checker_core (same directory)
try:
    from artwork_checker_core import validate_vision_overrides
except ImportError:
    # Allow running from a different CWD
    import importlib.util
    _core = Path(__file__).parent / "artwork_checker_core.py"
    _spec = importlib.util.spec_from_file_location("artwork_checker_core", str(_core))
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    validate_vision_overrides = _mod.validate_vision_overrides


def _check_item_states(overrides_path: Path, output_dir: Path) -> list[str]:
    """
    Per-item structural checks beyond what validate_vision_overrides() enforces.
    Returns a list of human-readable issue strings (empty = all clean).
    """
    issues = []
    try:
        raw = json.loads(overrides_path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"Cannot parse overrides file: {e}"]

    for o in raw.get("overrides", []):
        fid = o.get("finding_id", "?")
        found = o.get("found", False)
        value = (o.get("visual_artwork_value") or "").strip()
        confirmed = o.get("confirmed", False)

        if found and not value:
            issues.append(
                f"  [{fid}] found=true but visual_artwork_value is empty. "
                "Either set the value or change found to false."
            )
        if not found and value:
            issues.append(
                f"  [{fid}] found=false but visual_artwork_value is set ('{value}'). "
                "Either set found=true or clear the value."
            )
        if confirmed is not True:
            issues.append(f"  [{fid}] confirmed is not true (got: {confirmed!r}).")

        evp = (o.get("evidence_path") or "").strip()
        if evp:
            evp_path = Path(evp)
            if not evp_path.is_absolute():
                evp_path = output_dir / evp_path
            if not evp_path.exists():
                issues.append(
                    f"  [{fid}] evidence_path not found on disk: {o.get('evidence_path')}"
                )

    return issues


def _fail(errors: list[str], exit_code: int = 1) -> None:
    """Print VALIDATE_OVERRIDES_FAIL token to stderr and exit."""
    fail_data = {"errors": [e.strip() for e in errors]}
    print(
        f"VALIDATE_OVERRIDES_FAIL: {json.dumps(fail_data, ensure_ascii=False, sort_keys=True)}",
        file=sys.stderr,
        flush=True,
    )
    sys.exit(exit_code)


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

    # --- Check files exist ---
    if not overrides_path.exists():
        print(f"ERROR: overrides file not found: {overrides_path}", file=sys.stderr)
        _fail([f"overrides file not found: {overrides_path}"], exit_code=2)

    tasks_path = output_dir / "gpt_vision" / "vision_tasks.json"
    if not tasks_path.exists():
        print(f"ERROR: vision_tasks.json not found: {tasks_path}", file=sys.stderr)
        print("Run Pass 1 first.", file=sys.stderr)
        _fail([f"vision_tasks.json not found: {tasks_path} — run Pass 1 first."], exit_code=2)

    # --- Run structural validation ---
    try:
        validate_vision_overrides(
            output_dir=str(output_dir),
            vision_overrides_path=str(overrides_path),
            check_human_token=True,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"FAIL — structural validation error:\n  {e}\n", file=sys.stderr)
        item_issues = _check_item_states(overrides_path, output_dir)
        if item_issues:
            print("Per-item issues detected:", file=sys.stderr)
            for issue in item_issues:
                print(issue, file=sys.stderr)
        print(f"\n{sep}", file=sys.stderr)
        errors = [str(e)] + [i.strip() for i in item_issues]
        _fail(errors, exit_code=1)

    # --- Per-item diagnostics (belt-and-suspenders) ---
    item_issues = _check_item_states(overrides_path, output_dir)
    if item_issues:
        print("FAIL — per-item issues:", file=sys.stderr)
        for issue in item_issues:
            print(issue, file=sys.stderr)
        print(f"\n{sep}", file=sys.stderr)
        _fail(item_issues, exit_code=1)

    # --- All good ---
    raw = json.loads(overrides_path.read_text(encoding="utf-8"))
    n = len(raw.get("overrides", []))
    confirmed = sum(1 for o in raw.get("overrides", []) if o.get("confirmed") is True)
    found_true = sum(1 for o in raw.get("overrides", []) if o.get("found") is True)

    print(f"  Items total  : {n}")
    print(f"  confirmed    : {confirmed}/{n}")
    print(f"  found=true   : {found_true}/{n}")
    print(f"\n{sep}\n")

    token_data = {"confirmed": confirmed, "found_true": found_true, "items_total": n}
    print(
        f"VALIDATE_OVERRIDES_PASS: {json.dumps(token_data, ensure_ascii=False, sort_keys=True)}",
        flush=True,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
