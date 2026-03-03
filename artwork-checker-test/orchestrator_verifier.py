#!/usr/bin/env python3
"""
orchestrator_verifier.py — Deterministic wrapper-output parser.

Reads the last 5 lines of a wrapper stdout file, finds the
PASS1_WRAPPER_RESULT: or PASS2_WRAPPER_RESULT: JSON footer, and
prints exactly ONE canonical token to stdout.

Canonical tokens (stdout, one line):
  PASS1_ARTIFACTS_VERIFIED   — pass1 succeeded, all artifacts present
  PASS1_NO_PDF               — pass1 ran, no PDF, vision skipped
  PASS1_FAILED               — pass1 failed or artifacts missing
  PASS2_COMPLETE             — pass2 succeeded
  PASS2_FAILED               — pass2 failed or preflight rejected

Exit codes:
  0  — success token (PASS1_ARTIFACTS_VERIFIED, PASS1_NO_PDF, PASS2_COMPLETE)
  1  — failure token (PASS1_FAILED, PASS2_FAILED)
  2  — footer not found in wrapper output

Usage:
  python orchestrator_verifier.py --wrapper-output <file>
  python orchestrator_verifier.py --wrapper-output <file> --wrapper-type pass2
"""

import argparse
import json
import sys
from pathlib import Path

_PASS1_PREFIX = "PASS1_WRAPPER_RESULT:"
_PASS2_PREFIX = "PASS2_WRAPPER_RESULT:"

# Status → (canonical_token, exit_code)
_PASS1_STATUS_MAP = {
    "VERIFIED":         ("PASS1_ARTIFACTS_VERIFIED", 0),
    "NO_PDF":           ("PASS1_NO_PDF",             0),
    "ARTIFACT_MISSING": ("PASS1_FAILED",             1),
    "FAILED":           ("PASS1_FAILED",             1),
}

_PASS2_STATUS_MAP = {
    "PASS2_COMPLETE":    ("PASS2_COMPLETE", 0),
    "PASS2_FAILED":      ("PASS2_FAILED",   1),
    "PREFLIGHT_FAILED":  ("PASS2_FAILED",   1),
}


def _find_footer(lines: list[str], wrapper_type: str | None) -> tuple[str, dict] | None:
    """
    Search the last 5 lines for a PASS1_WRAPPER_RESULT: or PASS2_WRAPPER_RESULT:
    footer. Returns (prefix_key, parsed_json) or None.
    """
    prefixes = []
    if wrapper_type == "pass1":
        prefixes = [_PASS1_PREFIX]
    elif wrapper_type == "pass2":
        prefixes = [_PASS2_PREFIX]
    else:
        prefixes = [_PASS1_PREFIX, _PASS2_PREFIX]

    for line in reversed(lines[-5:]):
        stripped = line.strip()
        for prefix in prefixes:
            if stripped.startswith(prefix):
                json_part = stripped[len(prefix):].strip()
                try:
                    data = json.loads(json_part)
                    return (prefix, data)
                except json.JSONDecodeError:
                    return None
    return None


def _resolve_token(prefix: str, data: dict) -> tuple[str, int]:
    """Map footer JSON to (canonical_token, exit_code)."""
    status = data.get("status", "")
    if prefix == _PASS1_PREFIX:
        return _PASS1_STATUS_MAP.get(status, ("PASS1_FAILED", 1))
    else:
        return _PASS2_STATUS_MAP.get(status, ("PASS2_FAILED", 1))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse wrapper stdout and emit a single canonical phase token.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--wrapper-output", required=True, metavar="FILE",
        help="Path to file containing wrapper stdout",
    )
    parser.add_argument(
        "--wrapper-type", choices=["pass1", "pass2"], default=None,
        help="Hint: which wrapper produced the output (default: auto-detect)",
    )
    args = parser.parse_args()

    output_file = Path(args.wrapper_output)
    if not output_file.exists():
        # Use PASS1_FAILED as the safe default when the output file doesn't exist
        print("PASS1_FAILED")
        sys.exit(2)

    lines = output_file.read_text(encoding="utf-8", errors="replace").splitlines()

    result = _find_footer(lines, args.wrapper_type)
    if result is None:
        # Footer not found — determine which "failed" token to use
        default_fail = "PASS2_FAILED" if args.wrapper_type == "pass2" else "PASS1_FAILED"
        print(default_fail)
        sys.exit(2)

    prefix, data = result
    token, exit_code = _resolve_token(prefix, data)
    print(token)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
