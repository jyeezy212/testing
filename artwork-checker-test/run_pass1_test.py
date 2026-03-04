#!/usr/bin/env python3
"""
run_pass1_test.py — Pass 1 analysis preview (sections 1, 2, 3A, 3B, 3C, 3D).

Runs the copy document extraction + artwork matching pipeline and prints
the first four report sections without generating vision artifacts.

Usage:
  python run_pass1_test.py                         # lists available test files
  python run_pass1_test.py --copy "test_files/..." --artwork "test_files/..."
  python run_pass1_test.py --copy "..." --artwork "..." --output report.md
"""

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Windows terminals default to cp1252 which can't print emoji — force UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Allow running from any directory by adding the script's parent to path
sys.path.insert(0, str(Path(__file__).parent))

from artwork_checker_core import (
    ArtworkMatcher,
    ClaimRiskAssessor,
    ConversionChecker,
    CopyQualityChecker,
    ExcelCopyExtractor,
    ExtractionMethod,
    ExtractionResult,
    MarkdownRenderer,
    PDFExtractor,
    AIExtractor,
)

TEST_FILES_DIR = Path(__file__).parent / "test_files"


def _list_test_files() -> None:
    """Print available test files and exit."""
    print("Available test files:")
    print(f"  {TEST_FILES_DIR}/")
    if not TEST_FILES_DIR.exists():
        print("  (directory not found)")
        return
    for f in sorted(TEST_FILES_DIR.iterdir()):
        tag = ""
        if f.suffix.lower() == ".xlsx":
            tag = "  [copy doc]"
        elif f.suffix.lower() == ".pdf":
            tag = "  [artwork]"
        elif f.suffix.lower() == ".ai":
            tag = "  [artwork (AI)]"
        print(f"  {f.name}{tag}")


def _extract_artwork(
    artwork_path: Path,
    pdf_extractor: PDFExtractor,
    ai_extractor: AIExtractor,
) -> ExtractionResult:
    suffix = artwork_path.suffix.lower()
    if suffix == ".pdf":
        return pdf_extractor.extract(artwork_path)
    elif suffix == ".ai":
        return ai_extractor.extract(artwork_path)
    else:
        raise ValueError(f"Unsupported artwork format: {artwork_path.suffix!r}")


def _print_utf8(text: str) -> None:
    """Write text to stdout as UTF-8, bypassing any encoding errors."""
    try:
        sys.stdout.buffer.write(text.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.flush()
    except AttributeError:
        print(text)


def run(copy_path: Path, artwork_path: Path) -> str:
    """
    Run the Pass 1 analysis pipeline and return the markdown report
    for sections 1, 2, 3A, 3B, 3C, 3D.
    """
    sep = "=" * 60

    print(sep)
    print("PASS 1 TEST — Analysis Preview")
    print(sep)
    print(f"Copy document : {copy_path.name}")
    print(f"Artwork       : {artwork_path.name}")
    print(sep)

    # ── Step 1: Extract copy document ───────────────────────────────────────
    print("[1/5] Extracting copy document...")
    copy_extractor = ExcelCopyExtractor()
    copy_doc = copy_extractor.extract(copy_path)
    langs = copy_doc.metadata.get("languages_found", [])
    print(f"  Fields       : {len(copy_doc.fields)}")
    print(f"  Instructional: {len(copy_doc.instructional_fields)}")
    print(f"  Languages    : {langs}")
    print(f"  Project      : {copy_doc.project_name}")
    for w in copy_doc.warnings:
        print(f"  WARN: {w}")

    # ── Step 2: Extract artwork ──────────────────────────────────────────────
    print("\n[2/5] Extracting artwork...")
    pdf_extractor = PDFExtractor()
    ai_extractor = AIExtractor()
    artwork_extraction = _extract_artwork(artwork_path, pdf_extractor, ai_extractor)
    print(f"  Method       : {artwork_extraction.extraction_method.value}")
    print(f"  Confidence   : {artwork_extraction.confidence:.0%}")
    print(f"  Text runs    : {len(artwork_extraction.text_runs)}")
    for w in artwork_extraction.warnings:
        print(f"  WARN: {w}")

    # ── Step 3: Copy quality — Section 3A ───────────────────────────────────
    print("\n[3/5] Analyzing copy quality (3A)...")
    copy_quality_issues = CopyQualityChecker.analyze_copy_document(copy_doc)
    print(f"  Issues found : {len(copy_quality_issues)}")

    # ── Step 4: Claim risk — Section 3B ─────────────────────────────────────
    print("\n[4/5] Assessing claim risks (3B)...")
    claim_risks = ClaimRiskAssessor.assess_all_claims(copy_doc)
    print(f"  Claims found : {len(claim_risks)}")

    # ── Step 5: Conversions + matching — Sections 3C / 3D ───────────────────
    print("\n[5/5] Running conversions (3C) and artwork matching (3D)...")
    conversions = ConversionChecker.check_conversions(copy_doc)
    matcher = ArtworkMatcher()
    match_findings = matcher.match_fields(
        copy_doc.fields,
        artwork_extraction.text_runs,
        artwork_extraction.extraction_method,
        copy_quality_issues,
    )
    ok_count = sum(1 for f in match_findings if f.status_code.value == "OK")
    attn_count = sum(1 for f in match_findings if f.status_code.value == "ATTN")
    fail_count = sum(1 for f in match_findings if f.status_code.value in ("FAIL", "TBD"))
    print(f"  Conversions  : {len(conversions)}")
    print(f"  Findings     : {len(match_findings)}  (OK={ok_count}, ATTN={attn_count}, FAIL/TBD={fail_count})")

    print(f"\n{sep}")
    print("Building report...")
    print(sep)

    # ── Build report ─────────────────────────────────────────────────────────
    parts = []
    parts.append("# Artwork Verification Report — Pass 1 Preview\n")
    parts.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
    parts.append(f"*Copy: `{copy_path.name}` | Artwork: `{artwork_path.name}`*\n")

    parts.append(MarkdownRenderer._section1(copy_doc))
    parts.append(MarkdownRenderer._section2(copy_doc, artwork_extraction))
    parts.append("\n## 3️⃣ Core Verification Tables\n")
    parts.append(MarkdownRenderer._section3a(copy_quality_issues))
    parts.append(MarkdownRenderer._section3b(claim_risks))
    parts.append(MarkdownRenderer._section3c(conversions))
    parts.append(MarkdownRenderer._section3d(match_findings, copy_doc))

    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pass 1 analysis preview — sections 1, 2, 3A, 3B, 3C, 3D",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_pass1_test.py --list
  python run_pass1_test.py \\
      --copy "test_files/1. Body Wash 400ml - Bottle.xlsx" \\
      --artwork "test_files/1. Amika_Body_BodyWash_400ML_FinalAW_060625.pdf"
  python run_pass1_test.py \\
      --copy "test_files/5_Body_Butter_250ml_-_Carton.xlsx" \\
      --artwork "test_files/5__Amika_Body_BodyButter_Carton_AW_090225_VC_22640.pdf" \\
      --output report_preview.md
        """,
    )
    parser.add_argument("--copy", "-c", type=Path,
                        help="Path to copy document (.xlsx)")
    parser.add_argument("--artwork", "-a", type=Path,
                        help="Path to artwork file (.pdf or .ai)")
    parser.add_argument("--output", "-o", type=Path,
                        help="Optional: save report to this .md file")
    parser.add_argument("--list", "-l", action="store_true",
                        help="List available test files and exit")
    args = parser.parse_args()

    if args.list or (args.copy is None and args.artwork is None):
        _list_test_files()
        if not args.list:
            print("\nProvide --copy and --artwork to run the analysis.")
        sys.exit(0)

    if args.copy is None:
        parser.error("--copy is required")
    if args.artwork is None:
        parser.error("--artwork is required")

    copy_path = args.copy
    artwork_path = args.artwork

    if not copy_path.exists():
        print(f"ERROR: Copy document not found: {copy_path.resolve()}", file=sys.stderr)
        sys.exit(1)
    if not artwork_path.exists():
        print(f"ERROR: Artwork not found: {artwork_path.resolve()}", file=sys.stderr)
        sys.exit(1)

    try:
        report = run(copy_path, artwork_path)
    except Exception as e:
        print("\n=== ERROR ===", file=sys.stderr)
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

    # ── Output ────────────────────────────────────────────────────────────────
    sep = "=" * 60
    print(f"\n{sep}")
    print("REPORT")
    print(sep)
    _print_utf8(report)

    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"\nReport saved: {args.output.resolve()}", file=sys.stderr)

    print(f"\n{sep}")
    print("Done.")
    print(sep)


if __name__ == "__main__":
    main()
