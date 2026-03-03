#!/usr/bin/env python3
"""
run_pass1_wrapper.py — Hardened wrapper around artwork_checker_pass1.py.

Guarantees:
  1. --output is resolved to an absolute path before being passed to Pass 1.
  2. Artifact existence is checked with a 2-second retry window (NFS/flush safety).
  3. A machine-parseable PASS1_WRAPPER_RESULT: {...} line is always the last line on stdout.
  4. Exits 42 only when returncode==42 AND all expected artifacts exist.
     Exits 0 when returncode==0 (no PDF, vision skipped).
     Exits 1 on any other outcome (fail-fast).

The calling GPT must NOT emit sentinel text unless stdout contains
`PASS 1 ARTIFACTS: VERIFIED`.

Usage:
  python run_pass1_wrapper.py --copy /mnt/data/doc.xlsx \\
      --artwork /mnt/data/art.pdf --output ./output
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time


def _wait_for_artifacts(paths, timeout=2.0):
    """
    Poll for artifact existence up to `timeout` seconds.
    Returns list of still-missing path strings.
    """
    deadline = time.monotonic() + timeout
    while True:
        missing = [str(p) for p in paths if not p.exists()]
        if not missing or time.monotonic() >= deadline:
            return missing
        time.sleep(0.05)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pass 1 wrapper — verifies artifacts and writes audit JSON"
    )
    parser.add_argument("--copy", required=True, help="Path to .xlsx copy document")
    parser.add_argument("--artwork", required=True, nargs="+",
                        help="Path to artwork file(s) (.pdf and/or .ai)")
    parser.add_argument("--output", default="./output", help="Output directory")
    args = parser.parse_args()

    # Resolve output to an absolute path before passing through to Pass 1
    output = pathlib.Path(args.output).resolve()

    # Build pass1 command with resolved absolute output path
    # _ARTWORK_CHECKER_PASS1_SCRIPT env var allows test injection of a fake script
    pass1 = pathlib.Path(
        os.environ.get("_ARTWORK_CHECKER_PASS1_SCRIPT")
        or str(pathlib.Path(__file__).parent / "artwork_checker_pass1.py")
    )
    cmd = (
        [sys.executable, str(pass1), "--copy", args.copy, "--artwork"]
        + args.artwork
        + ["--output", str(output)]
    )

    proc = subprocess.run(cmd, capture_output=True, text=True)

    # ------------------------------------------------------------------
    # Verify expected artifacts with retry window (NFS / OS flush safety)
    # ------------------------------------------------------------------
    expected = [
        output / ".PASS1_DONE",
        output / ".HUMAN_TOKEN",
        output / "gpt_vision" / "vision_tasks.json",
        output / "gpt_vision" / "vision_overrides.prefill.json",
    ]
    missing = _wait_for_artifacts(expected, timeout=2.0)

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
        "output_dir": str(output),
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
    # Determine result and exit code
    # Rule: exit 42 only when returncode==42 AND no missing artifacts.
    #       exit 0  when returncode==0 (no PDF, vision skipped).
    #       exit 1  on any other outcome (fail-fast).
    # ------------------------------------------------------------------
    sep = "=" * 60
    print(f"\n{sep}")

    if proc.returncode == 42 and not missing:
        status = "VERIFIED"
        exit_code = 42
        print("PASS 1 ARTIFACTS: VERIFIED — all expected files present")

    elif proc.returncode == 0:
        status = "NO_PDF"
        exit_code = 0
        print("PASS 1 COMPLETE — no PDF provided, vision skipped")

    elif proc.returncode == 42 and missing:
        # Pass 1 claimed success (exit 42) but artifacts are missing
        status = "ARTIFACT_MISSING"
        exit_code = 1
        print(f"PASS 1 ARTIFACT ERROR — output dir: {output}")
        print(f"Missing files: {missing}")
        print("Do NOT emit sentinel text. Show this error to the user.")

    else:
        # Pass 1 itself failed (non-zero, non-42 returncode)
        status = "FAILED"
        exit_code = 1
        print(f"PASS 1 FAILED — returncode {proc.returncode}, output dir: {output}")
        if missing:
            print(f"Also missing artifacts: {missing}")
        try:
            print(proc.stderr)
        except UnicodeEncodeError:
            sys.stdout.buffer.write(proc.stderr.encode("utf-8", errors="replace"))

    print(sep)

    # ------------------------------------------------------------------
    # Machine-parseable footer — MUST be the last line on stdout
    # ------------------------------------------------------------------
    footer = {
        "exit_code": exit_code,
        "human_token": human_token,
        "missing": missing,
        "output_dir": str(output),
        "returncode": proc.returncode,
        "status": status,
        "stderr_snippet": proc.stderr[:500] if proc.stderr else "",
    }
    print(
        f"PASS1_WRAPPER_RESULT: {json.dumps(footer, ensure_ascii=False, sort_keys=True)}",
        flush=True,
    )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
