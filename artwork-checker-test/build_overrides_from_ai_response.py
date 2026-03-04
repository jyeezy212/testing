#!/usr/bin/env python3
"""
build_overrides_from_ai_response.py — Bridge between AI JSON output and vision_overrides.json.

The AI cannot compute SHA256 hashes. This script:
  1. Accepts the AI's JSON response (via --ai-json or --ai-json-file).
  2. Fills in source_image_sha256 for each override item by reading the file.
  3. Computes char_count, punctuation_signature, has_diacritics from visual_artwork_value
     (if missing or mismatched, corrects them and warns).
  4. Writes the completed vision_overrides.json.
  5. Runs validate_overrides_cli.py.

Usage:
  # From a file containing the AI's JSON block
  python build_overrides_from_ai_response.py \\
      --output ./output \\
      --ai-json-file ai_response.json

  # From a JSON string (e.g. piped from another script)
  python build_overrides_from_ai_response.py \\
      --output ./output \\
      --ai-json '{"vision_audit": {...}, "overrides": [...]}'

  # Skip auto-validate (just write the file)
  python build_overrides_from_ai_response.py \\
      --output ./output --ai-json-file ai_response.json --no-validate
"""

import argparse
import hashlib
import json
import string
import subprocess
import sys
import unicodedata
from pathlib import Path


# ---------------------------------------------------------------------------
# Pure helpers (mirrors of validate_overrides_cli.py)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(
    ai_json: dict,
    output_dir: Path,
    overrides_out: Path,
    *,
    run_validate: bool = True,
) -> bool:
    """
    Enrich the AI JSON with computed fields, write vision_overrides.json,
    optionally validate.  Returns True if validate passed (or skipped).
    """
    overrides = ai_json.get("overrides", [])
    warnings = []

    for o in overrides:
        fid = o.get("finding_id", "?")
        found = o.get("found", False)
        value = (o.get("visual_artwork_value") or "").strip()
        source_image = (o.get("source_image") or "").strip()

        # ── SHA256 ──────────────────────────────────────────────────────
        if source_image:
            abs_src = Path(source_image)
            if not abs_src.is_absolute():
                abs_src = output_dir / source_image
            if abs_src.exists():
                sha = _sha256_file(abs_src)
                existing_sha = (o.get("source_image_sha256") or "").strip()
                if existing_sha and existing_sha != sha:
                    warnings.append(
                        f"[{fid}] source_image_sha256 provided by AI ({existing_sha[:8]}…) "
                        f"does not match actual file ({sha[:8]}…) — replaced."
                    )
                o["source_image_sha256"] = sha
            else:
                warnings.append(
                    f"[{fid}] source_image '{source_image}' not found on disk — "
                    "SHA256 cannot be computed."
                )
        else:
            warnings.append(f"[{fid}] source_image is missing — SHA256 skipped.")

        # ── Self-consistency fields ─────────────────────────────────────
        if found and value:
            cc = _char_count(value)
            ps = _punctuation_signature(value)
            hd = _has_diacritics(value)

            if o.get("char_count") is None or int(o.get("char_count", -1)) != cc:
                if o.get("char_count") is not None:
                    warnings.append(
                        f"[{fid}] char_count corrected: {o['char_count']} → {cc}"
                    )
                o["char_count"] = cc

            if o.get("punctuation_signature") is None or list(o.get("punctuation_signature", [])) != ps:
                o["punctuation_signature"] = ps

            if o.get("has_diacritics") is None or bool(o.get("has_diacritics")) != hd:
                o["has_diacritics"] = hd
        else:
            # found=false or empty value — set defaults
            if o.get("char_count") is None:
                o["char_count"] = 0
            if o.get("punctuation_signature") is None:
                o["punctuation_signature"] = []
            if o.get("has_diacritics") is None:
                o["has_diacritics"] = False

    # Print warnings
    for w in warnings:
        print(f"  WARN: {w}", file=sys.stderr)

    # Write completed file
    output_dir.mkdir(parents=True, exist_ok=True)
    overrides_out.write_text(
        json.dumps(ai_json, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Written: {overrides_out}")

    if not run_validate:
        return True

    # Run validate
    cli = Path(__file__).parent / "validate_overrides_cli.py"
    if not cli.exists():
        print("WARNING: validate_overrides_cli.py not found — skipping.", file=sys.stderr)
        return True

    result = subprocess.run(
        [sys.executable, str(cli),
         "--output", str(output_dir),
         "--overrides", str(overrides_out)],
        capture_output=False,  # let output flow through
    )
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build vision_overrides.json from AI response JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=Path("./output"),
        help="Output directory from Pass 1 (default: ./output)",
    )

    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--ai-json", metavar="JSON",
        help="AI response as a JSON string",
    )
    src.add_argument(
        "--ai-json-file", type=Path, metavar="FILE",
        help="Path to a file containing the AI response JSON",
    )

    parser.add_argument(
        "--overrides-out", type=Path, default=None,
        help="Where to write vision_overrides.json (default: <output>/vision_overrides.json)",
    )
    parser.add_argument(
        "--no-validate", action="store_true",
        help="Write the file but skip running validate_overrides_cli.py",
    )
    args = parser.parse_args()

    output_dir = args.output.resolve()
    overrides_out = args.overrides_out or (output_dir / "vision_overrides.json")

    # Load AI JSON
    if args.ai_json:
        raw_text = args.ai_json
    else:
        ai_file = args.ai_json_file
        if not ai_file.exists():
            print(f"ERROR: --ai-json-file not found: {ai_file}", file=sys.stderr)
            sys.exit(1)
        raw_text = ai_file.read_text(encoding="utf-8")

    # Strip markdown code fences if present (```json ... ```)
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Remove first and last fence lines
        inner = lines[1:] if lines[0].startswith("```") else lines
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        stripped = "\n".join(inner)

    try:
        ai_json = json.loads(stripped)
    except json.JSONDecodeError as e:
        print(f"ERROR: Cannot parse AI JSON: {e}", file=sys.stderr)
        print("Make sure the AI responded with a raw JSON block only.", file=sys.stderr)
        sys.exit(1)

    sep = "=" * 60
    print(f"\n{sep}")
    print("BUILD OVERRIDES FROM AI RESPONSE")
    print(f"{sep}")
    print(f"  Output dir   : {output_dir}")
    print(f"  Overrides out: {overrides_out}")
    print(f"  Items        : {len(ai_json.get('overrides', []))}")
    print()

    ok = process(
        ai_json,
        output_dir,
        overrides_out,
        run_validate=not args.no_validate,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
