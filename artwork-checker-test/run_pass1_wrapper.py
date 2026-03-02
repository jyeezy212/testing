#!/usr/bin/env python3
"""
run_pass1_wrapper.py — Thin wrapper around artwork_checker_pass1.py.

Runs Pass 1, verifies expected artifacts exist, writes an audit JSON file,
then prints the original Pass 1 stdout verbatim followed by a verification
line. The calling GPT must NOT emit sentinel text unless this wrapper's
stdout contains `PASS 1 ARTIFACTS: VERIFIED`.

Usage:
  python run_pass1_wrapper.py --copy /mnt/data/doc.xlsx \\
      --artwork /mnt/data/art.pdf --output ./output
"""

import argparse
import json
import pathlib
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pass 1 wrapper — verifies artifacts and writes audit JSON"
    )
    parser.add_argument("--copy", required=True, help="Path to .xlsx copy document")
    parser.add_argument("--artwork", required=True, nargs="+",
                        help="Path to artwork file(s) (.pdf and/or .ai)")
    parser.add_argument("--output", default="./output", help="Output directory")
    args = parser.parse_args()

    output = pathlib.Path(args.output)

    # Build pass1 command (mirrors pass1 CLI exactly)
    pass1 = pathlib.Path(__file__).parent / "artwork_checker_pass1.py"
    cmd = (
        [sys.executable, str(pass1), "--copy", args.copy, "--artwork"]
        + args.artwork
        + ["--output", str(output)]
    )

    proc = subprocess.run(cmd, capture_output=True, text=True)

    # ------------------------------------------------------------------
    # Verify expected artifacts
    # ------------------------------------------------------------------
    expected = [
        output / ".PASS1_DONE",
        output / ".HUMAN_TOKEN",
        output / "gpt_vision" / "vision_tasks.json",
        output / "gpt_vision" / "vision_overrides.prefill.json",
    ]
    missing = [str(p) for p in expected if not p.exists()]

    # Read human token if present
    human_token = None
    token_path = output / ".HUMAN_TOKEN"
    if token_path.exists():
        try:
            human_token = token_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    # Read pass1 summary if present
    pass1_summary = None
    summary_path = output / ".pass1_summary.json"
    if summary_path.exists():
        try:
            pass1_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Write audit JSON (machine-readable record for debugging)
    # ------------------------------------------------------------------
    audit = {
        "returncode": proc.returncode,
        "missing": missing,
        "human_token": human_token,
        "pass1_summary": pass1_summary,
        "stderr_snippet": proc.stderr[:500] if proc.stderr else "",
    }
    try:
        output.mkdir(parents=True, exist_ok=True)
        (output / ".pass1_wrapper_result.json").write_text(
            json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass  # non-fatal — stdout output is the primary contract

    # ------------------------------------------------------------------
    # Print pass1 stdout verbatim (GPT reads this as the script output)
    # ------------------------------------------------------------------
    try:
        print(proc.stdout, end="")
    except UnicodeEncodeError:
        sys.stdout.buffer.write(proc.stdout.encode("utf-8", errors="replace"))

    # ------------------------------------------------------------------
    # Print artifact verification result — GPT gates sentinel on this line
    # ------------------------------------------------------------------
    sep = "=" * 60
    print(f"\n{sep}")
    if proc.returncode == 42 and not missing:
        print("PASS 1 ARTIFACTS: VERIFIED — all expected files present")
    elif proc.returncode == 0:
        print("PASS 1 COMPLETE — no PDF provided, vision skipped")
    elif missing:
        print(f"PASS 1 ARTIFACT ERROR — missing files: {missing}")
        print("Do NOT emit sentinel text. Show this error to the user.")
        if proc.returncode not in (0, 42):
            try:
                print(proc.stderr)
            except UnicodeEncodeError:
                sys.stdout.buffer.write(proc.stderr.encode("utf-8", errors="replace"))
    else:
        print("PASS 1 FAILED — script returned non-zero; see stderr below")
        try:
            print(proc.stderr)
        except UnicodeEncodeError:
            sys.stdout.buffer.write(proc.stderr.encode("utf-8", errors="replace"))
    print(sep)

    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
