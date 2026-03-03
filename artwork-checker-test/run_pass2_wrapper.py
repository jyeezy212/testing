#!/usr/bin/env python3
"""
run_pass2_wrapper.py — Safe wrapper around artwork_checker_pass2.py.

Runs preflight validation of vision_overrides.json BEFORE invoking Pass 2.
If validation fails, prints a clear actionable error and exits without running
Pass 2. If validation passes, delegates to artwork_checker_pass2.py verbatim.

The calling GPT must NOT treat a non-zero exit as a transient error — every
failure is structural and requires the overrides file to be corrected first.

Machine footer (always last line on stdout):
  PASS2_WRAPPER_RESULT: {...}
  status: PASS2_COMPLETE | PASS2_FAILED | PREFLIGHT_FAILED

Usage:
  python run_pass2_wrapper.py \\
      --copy /mnt/data/doc.xlsx \\
      --artwork /mnt/data/art.pdf \\
      --output ./output \\
      --vision-overrides ./output/vision_overrides.json
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys

# Mirror of artwork_checker_core.REASON_NOT_FOUND_ALLOWED (belt-and-suspenders)
_REASON_NOT_FOUND_ALLOWED = frozenset({
    "not_present_on_artwork",
    "illegible",
    "not_in_provided_crops",
    "blocked_or_obscured",
    "language_variant_mismatch",
})


def _print_footer(
    status: str,
    returncode: int,
    exit_code: int,
    output_dir: pathlib.Path,
    stderr: str = "",
    report_path: str | None = None,
) -> None:
    """Print the machine-parseable footer. Must be the last line on stdout."""
    footer = {
        "exit_code": exit_code,
        "output_dir": str(output_dir),
        "report_path": report_path,
        "returncode": returncode,
        "status": status,
        "stderr_snippet": (stderr or "")[:500],
    }
    print(
        f"PASS2_WRAPPER_RESULT: {json.dumps(footer, ensure_ascii=False, sort_keys=True)}",
        flush=True,
    )


def _preflight(output_dir: pathlib.Path, overrides_path: pathlib.Path) -> list[str]:
    """
    Fast structural check before invoking Pass 2.
    Returns a list of human-readable error strings; empty means all clear.
    """
    errors = []

    # Required Pass 1 artifacts
    if not (output_dir / ".PASS1_DONE").exists():
        errors.append(
            "output/.PASS1_DONE not found — run Pass 1 first."
        )
    tasks_path = output_dir / "gpt_vision" / "vision_tasks.json"
    if not tasks_path.exists():
        errors.append(
            "output/gpt_vision/vision_tasks.json not found — run Pass 1 first."
        )

    if not overrides_path.exists():
        errors.append(
            f"vision_overrides file not found: {overrides_path}\n"
            "  Fill in vision_overrides.prefill.json then save as vision_overrides.json."
        )
        return errors  # can't continue without the file

    token_path = output_dir / ".HUMAN_TOKEN"
    if not token_path.exists():
        errors.append("output/.HUMAN_TOKEN not found — re-run Pass 1.")
        return errors

    # Parse overrides
    try:
        raw = json.loads(overrides_path.read_text(encoding="utf-8"))
    except Exception as e:
        errors.append(f"Cannot parse vision_overrides.json: {e}")
        return errors

    # human_token match
    expected_token = token_path.read_text(encoding="utf-8").strip()
    audit = raw.get("vision_audit", {})
    provided_token = (audit.get("human_token") or "").strip()
    if not provided_token:
        errors.append(
            "vision_audit.human_token is empty.\n"
            f"  Expected: '{expected_token}'\n"
            "  The prefill file has the token pre-filled — do not remove it."
        )
    elif provided_token != expected_token:
        errors.append(
            "human_token mismatch.\n"
            f"  Expected : '{expected_token}'\n"
            f"  Provided : '{provided_token}'\n"
            "  Copy the token from vision_overrides.prefill.json without modification."
        )

    # Load tasks data once — used for both the empty-overrides check and Option A
    tasks_data: dict = {}
    item_match_types: dict = {}
    if tasks_path.exists():
        try:
            tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))
            item_match_types = {
                it["id"]: it.get("script_match_type", "")
                for it in tasks_data.get("items", [])
            }
        except Exception:
            pass

    # Per-item checks
    overrides = raw.get("overrides", [])
    if not overrides:
        required_ids = tasks_data.get("required_ids", [])
        if required_ids:
            errors.append(
                f"overrides list is empty but {len(required_ids)} vision item(s) require confirmation."
            )
        return errors  # no per-item checks for empty list

    for o in overrides:
        fid = o.get("finding_id", "?")
        found = bool(o.get("found", False))
        value = (o.get("visual_artwork_value") or "").strip()
        confirmed = o.get("confirmed", False)

        if confirmed is not True:
            errors.append(
                f"[{fid}] confirmed is not true — set confirmed: true after visual check."
            )
        if found and not value:
            errors.append(
                f"[{fid}] found=true but visual_artwork_value is empty.\n"
                "  Either type the visible text or set found: false if not present."
            )
        evp = (o.get("evidence_path") or "").strip()
        if evp:
            evp_path = pathlib.Path(evp)
            if not evp_path.is_absolute():
                evp_path = output_dir / evp_path
            if not evp_path.exists():
                errors.append(
                    f"[{fid}] evidence_path does not exist on disk: {o.get('evidence_path')}"
                )

        # Option A: non-exact items with found=false MUST supply reason_not_found
        match_type = item_match_types.get(fid, "")  # "" = unknown → non-exact
        if match_type != "exact" and not found:
            reason = (o.get("reason_not_found") or "").strip()
            if not reason:
                errors.append(
                    f"[{fid}] found=false but reason_not_found is missing.\n"
                    f"  Allowed values: {sorted(_REASON_NOT_FOUND_ALLOWED)}"
                )
            elif reason not in _REASON_NOT_FOUND_ALLOWED:
                errors.append(
                    f"[{fid}] reason_not_found '{reason}' is not allowed.\n"
                    f"  Allowed: {sorted(_REASON_NOT_FOUND_ALLOWED)}"
                )

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pass 2 wrapper — preflight validates then runs Pass 2"
    )
    parser.add_argument("--copy", required=True, help="Path to .xlsx copy document")
    parser.add_argument("--artwork", required=True, nargs="+",
                        help="Path to artwork file(s) (.pdf and/or .ai)")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--vision-overrides", required=True, dest="vision_overrides",
                        help="Path to completed vision_overrides.json")
    parser.add_argument("--no-snapshots", action="store_true",
                        help="Disable snapshot generation")
    args = parser.parse_args()

    output = pathlib.Path(args.output).resolve()
    overrides = pathlib.Path(args.vision_overrides)

    sep = "=" * 60

    # ------------------------------------------------------------------
    # Preflight validation — refuse to run Pass 2 if anything is wrong
    # ------------------------------------------------------------------
    errors = _preflight(output, overrides)
    if errors:
        print(f"\n{sep}", file=sys.stderr)
        print("PASS 2 PREFLIGHT FAILED — fix the following before retrying:", file=sys.stderr)
        for i, err in enumerate(errors, 1):
            print(f"\n[{i}] {err}", file=sys.stderr)
        print(f"\n{sep}", file=sys.stderr)
        print(f"\n{sep}")
        print("PASS 2 PREFLIGHT FAILED — see errors above.")
        print("Do NOT run Pass 2. Correct the vision_overrides.json file first.")
        print(sep)
        _print_footer("PREFLIGHT_FAILED", -1, 1, output)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Delegate to artwork_checker_pass2.py
    # ------------------------------------------------------------------
    # _ARTWORK_CHECKER_PASS2_SCRIPT env var allows test injection of a fake script
    pass2 = pathlib.Path(
        os.environ.get("_ARTWORK_CHECKER_PASS2_SCRIPT")
        or str(pathlib.Path(__file__).parent / "artwork_checker_pass2.py")
    )
    cmd = (
        [sys.executable, str(pass2), "--copy", args.copy, "--artwork"]
        + args.artwork
        + ["--output", str(output), "--vision-overrides", str(overrides)]
    )
    if args.no_snapshots:
        cmd.append("--no-snapshots")

    proc = subprocess.run(cmd, capture_output=True, text=True)

    # Print Pass 2 stdout verbatim
    try:
        print(proc.stdout, end="")
    except UnicodeEncodeError:
        sys.stdout.buffer.write(proc.stdout.encode("utf-8", errors="replace"))

    if proc.returncode != 0:
        try:
            print(proc.stderr, end="", file=sys.stderr)
        except UnicodeEncodeError:
            sys.stderr.buffer.write(proc.stderr.encode("utf-8", errors="replace"))
        _print_footer("PASS2_FAILED", proc.returncode, 1, output, proc.stderr)
        sys.exit(1)
    else:
        _print_footer("PASS2_COMPLETE", proc.returncode, 0, output, proc.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
