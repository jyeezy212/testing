#!/usr/bin/env python3
"""
run_pass2_wrapper.py — Safe wrapper around artwork_checker_pass2.py.

Runs preflight validation of vision_overrides.json BEFORE invoking Pass 2.
If validation fails, prints a clear actionable error and exits without running
Pass 2. If validation passes, delegates to artwork_checker_pass2.py verbatim.

The calling GPT must NOT treat a non-zero exit as a transient error — every
failure is structural and requires the overrides file to be corrected first.

Usage:
  python run_pass2_wrapper.py \\
      --copy /mnt/data/doc.xlsx \\
      --artwork /mnt/data/art.pdf \\
      --output ./output \\
      --vision-overrides ./output/vision_overrides.json
"""

import argparse
import json
import pathlib
import subprocess
import sys


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

    # Per-item checks
    overrides = raw.get("overrides", [])
    if not overrides:
        errors.append("overrides list is empty.")
        return errors

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

    output = pathlib.Path(args.output)
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
        sys.exit(1)

    # ------------------------------------------------------------------
    # Delegate to artwork_checker_pass2.py
    # ------------------------------------------------------------------
    pass2 = pathlib.Path(__file__).parent / "artwork_checker_pass2.py"
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

    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
