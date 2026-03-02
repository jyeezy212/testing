#!/usr/bin/env python3
"""
================================================================================
ARTWORK CHECKER — PASS 2
================================================================================
Responsibilities:
  0. GATE — refuse to run unless ALL of the following exist and are valid:
       - output/.PASS1_DONE
       - output/gpt_vision/vision_tasks.json
       - --vision-overrides file (vision_overrides.json)
       - vision_audit.human_token matches output/.HUMAN_TOKEN
       - Full structural validation of overrides
  1. Re-extract copy document
  2. Re-extract artwork
  3. Copy quality analysis (Section A)
  4. Claim risk assessment (Section B)
  5. Conversion check + artwork matching (Sections C / D)
  6. Apply vision overrides (VisionOverrideApplier)
  7. Font extraction (Section E)
  8. Barcode scan (Section F)
  9. Snapshot generation (Section G)
 10. Render full markdown report
 11. Save report to output/artwork_check_report.md
 12. Print full report to stdout (all sections A–H, no truncation)
 13. Print snapshot section with inline ![...](...) tags for every PNG
 14. Exit 0

USAGE:
  python artwork_checker_pass2.py \\
    --copy doc.xlsx --artwork art.pdf --output ./output \\
    --vision-overrides ./output/vision_overrides.json
================================================================================
"""

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Import ALL needed classes from core (includes Pass 2-only classes)
# ---------------------------------------------------------------------------
from artwork_checker_core import (
    config,
    logger,
    validate_vision_overrides,
    ExcelCopyExtractor,
    PDFExtractor,
    AIExtractor,
    CopyQualityChecker,
    ClaimRiskAssessor,
    ConversionChecker,
    ArtworkMatcher,
    VisionOverrideApplier,
    FontExtractor,
    BarcodeScanner,
    SnapshotGenerator,
    MarkdownRenderer,
    ExtractionResult,
    ExtractionMethod,
    StatusCode,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PASS1_LOCK_FILE = ".PASS1_DONE"
HUMAN_TOKEN_FILE = ".HUMAN_TOKEN"


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

def gate_check(output_dir: Path, vision_overrides_path: Path) -> None:
    """
    Hard gate — abort with a clear error message if any precondition fails.
    Must run BEFORE any extraction work.
    """
    errors = []

    # 1. Lock file
    lock = output_dir / PASS1_LOCK_FILE
    if not lock.exists():
        errors.append(
            f"output/{PASS1_LOCK_FILE} not found. "
            "Run Pass 1 first:\n"
            "  python artwork_checker_pass1.py --copy ... --artwork ... --output ..."
        )

    # 2. vision_tasks.json
    tasks_path = output_dir / "gpt_vision" / "vision_tasks.json"
    if not tasks_path.exists():
        errors.append(
            f"output/gpt_vision/vision_tasks.json not found. "
            "Pass 1 must complete with a PDF artwork file to generate vision tasks."
        )

    # 3. vision_overrides.json
    if not vision_overrides_path.exists():
        errors.append(
            f"vision_overrides file not found: {vision_overrides_path}\n"
            "Fill in vision_overrides.prefill.json, then save it as vision_overrides.json."
        )

    if errors:
        _gate_fail(errors)

    # 4. Human token match
    token_path = output_dir / HUMAN_TOKEN_FILE
    if not token_path.exists():
        _gate_fail([
            f"output/{HUMAN_TOKEN_FILE} not found. "
            "Re-run Pass 1 to generate a fresh token."
        ])

    expected_token = token_path.read_text(encoding="utf-8").strip()
    try:
        raw = json.loads(vision_overrides_path.read_text(encoding="utf-8"))
    except Exception as e:
        _gate_fail([f"Could not parse vision_overrides.json: {e}"])
        return  # unreachable but keeps linter happy

    audit = raw.get("vision_audit", {})
    provided_token = (audit.get("human_token") or "").strip()

    if not provided_token:
        _gate_fail([
            "GATE FAILED: vision_audit.human_token is empty in vision_overrides.json.\n"
            f"  Expected: '{expected_token}' (from output/{HUMAN_TOKEN_FILE})\n"
            "  Open vision_overrides.prefill.json — the token is pre-filled. "
            "Copy it to your vision_overrides.json."
        ])

    if provided_token != expected_token:
        _gate_fail([
            "GATE FAILED: human_token mismatch.\n"
            f"  Expected : '{expected_token}' (from output/{HUMAN_TOKEN_FILE})\n"
            f"  Provided : '{provided_token}' (from vision_overrides.json)\n"
            "This token must match exactly. "
            "Do not modify it — copy from vision_overrides.prefill.json."
        ])

    # 5. Full structural validation (task_hash, IDs, confirmed, evidence)
    try:
        validate_vision_overrides(
            output_dir=str(output_dir),
            vision_overrides_path=str(vision_overrides_path),
            check_human_token=False,  # already checked above; avoids re-reading file
        )
    except (ValueError, FileNotFoundError) as e:
        _gate_fail([str(e)])


def _gate_fail(errors: List[str]) -> None:
    """Print all gate errors and exit 1."""
    print("\n=== PASS 2 GATE FAILED ===", file=sys.stderr)
    for i, err in enumerate(errors, 1):
        print(f"\n[{i}] {err}", file=sys.stderr)
    print("\n===========================", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Artwork extraction helper (same logic as Pass 1)
# ---------------------------------------------------------------------------

def _extract_artwork(artwork_paths, pdf_extractor, ai_extractor):
    pdf_paths = [p for p in artwork_paths if p.suffix.lower() == ".pdf"]
    ai_paths = [p for p in artwork_paths if p.suffix.lower() == ".ai"]

    for pdf_path in pdf_paths:
        extraction = pdf_extractor.extract(pdf_path)
        if extraction.confidence > 0:
            return extraction, pdf_path

    for ai_path in ai_paths:
        extraction = ai_extractor.extract(ai_path)
        if extraction.confidence > 0:
            return extraction, ai_path

    fallback_path = artwork_paths[0]
    return ExtractionResult(
        file_path=str(fallback_path),
        file_type=fallback_path.suffix.lower().lstrip("."),
        extraction_method=ExtractionMethod.FAILED,
        confidence=0.0,
        warnings=["All artwork extraction methods failed"],
    ), fallback_path


# ---------------------------------------------------------------------------
# Pass 2 runner
# ---------------------------------------------------------------------------

def run_pass2(
    copy_path: Path,
    artwork_paths: List[Path],
    output_dir: Path,
    vision_overrides_path: Path,
    no_snapshots: bool = False,
) -> str:
    """
    Execute Pass 2 pipeline.  Gate is checked first — raises SystemExit on failure.
    Returns the full markdown report string.
    """
    logger.info("=" * 60)
    logger.info(f"ARTWORK CHECKER PASS 2 — v{config.VERSION}")
    logger.info("=" * 60)

    copy_path = Path(copy_path)
    artwork_paths = [Path(p) for p in artwork_paths]
    output_dir = Path(output_dir)
    vision_overrides_path = Path(vision_overrides_path)

    # ------------------------------------------------------------------
    # GATE — must pass before any extraction work
    # ------------------------------------------------------------------
    logger.info("\n[GATE] Validating Pass 1 artifacts and vision overrides...")
    gate_check(output_dir, vision_overrides_path)
    logger.info("  Gate passed.")

    if not copy_path.exists():
        raise FileNotFoundError(f"Copy document not found: {copy_path}")
    for ap in artwork_paths:
        if not ap.exists():
            raise FileNotFoundError(f"Artwork file not found: {ap}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 1: Extract copy document (re-run to rebuild in-memory state)
    # ------------------------------------------------------------------
    logger.info("\n[1/7] Extracting copy document...")
    copy_extractor = ExcelCopyExtractor()
    copy_doc = copy_extractor.extract(copy_path)
    logger.info(f"  - Fields: {len(copy_doc.fields)}, Instructional: {len(copy_doc.instructional_fields)}")
    logger.info(f"  - Languages: {copy_doc.metadata.get('languages_found', [])}")
    logger.info(f"  - Project: {copy_doc.project_name}")
    for w in copy_doc.warnings:
        logger.warning(f"  {w}")

    # ------------------------------------------------------------------
    # Step 2: Extract artwork
    # ------------------------------------------------------------------
    logger.info("\n[2/7] Extracting artwork...")
    pdf_extractor = PDFExtractor()
    ai_extractor = AIExtractor()
    artwork_extraction, artwork_path_used = _extract_artwork(
        artwork_paths, pdf_extractor, ai_extractor
    )
    logger.info(f"  - File: {artwork_path_used.name}")
    logger.info(f"  - Method: {artwork_extraction.extraction_method.value}")
    logger.info(f"  - Text runs: {len(artwork_extraction.text_runs)}")

    # ------------------------------------------------------------------
    # Step 3: Copy quality (Section A)
    # ------------------------------------------------------------------
    logger.info("\n[3/7] Analyzing copy quality...")
    copy_quality_issues = CopyQualityChecker.analyze_copy_document(copy_doc)
    logger.info(f"  - Issues: {len(copy_quality_issues)}")

    # ------------------------------------------------------------------
    # Step 4: Claim risk (Section B)
    # ------------------------------------------------------------------
    logger.info("\n[4/7] Assessing claim risks...")
    claim_risks = ClaimRiskAssessor.assess_all_claims(copy_doc)
    logger.info(f"  - Claims: {len(claim_risks)}")

    # ------------------------------------------------------------------
    # Step 5: Conversions + matching (Sections C / D)
    # ------------------------------------------------------------------
    logger.info("\n[5/7] Running conversions and artwork matching...")
    conversions = ConversionChecker.check_conversions(copy_doc)
    matcher = ArtworkMatcher()
    match_findings = matcher.match_fields(
        copy_doc.fields,
        artwork_extraction.text_runs,
        artwork_extraction.extraction_method,
        copy_quality_issues,
    )

    # ------------------------------------------------------------------
    # Step 6: Apply vision overrides
    # ------------------------------------------------------------------
    logger.info(f"\n[6/7] Applying vision overrides from {vision_overrides_path}...")
    vision_applier = VisionOverrideApplier()
    vision_applier.apply(match_findings, vision_overrides_path)

    # ------------------------------------------------------------------
    # Step 7: Font + Barcode + Snapshots (all PDF-only)
    # ------------------------------------------------------------------
    logger.info("\n[7/7] Font, barcode, and snapshot generation...")
    font_measurements = []
    barcode_results = []
    snapshot_paths = []

    is_pdf = artwork_path_used and artwork_path_used.suffix.lower() == ".pdf"

    if is_pdf:
        font_extractor = FontExtractor()
        font_measurements = font_extractor.extract_from_pdf(artwork_path_used)
        logger.info(f"  - Font measurements: {len(font_measurements)}")

        barcode_results = BarcodeScanner.scan_from_pdf(artwork_path_used)
        logger.info(f"  - Barcode results: {len(barcode_results)}")

        if config.SNAPSHOT_ENABLED and not no_snapshots:
            snap_gen = SnapshotGenerator()
            snap_objs = snap_gen.generate_snapshots(
                artwork_path_used, match_findings, output_dir / "snapshots"
            )
            snapshot_paths = [str(p) for p in snap_objs]
            logger.info(f"  - Snapshots: {len(snapshot_paths)}")
    else:
        logger.warning("  Artwork is not a PDF — font/barcode/snapshot extraction skipped.")

    # ------------------------------------------------------------------
    # Generate report
    # ------------------------------------------------------------------
    logger.info("\nGenerating markdown report...")
    report = MarkdownRenderer.render_complete_report(
        copy_doc=copy_doc,
        artwork_extraction=artwork_extraction,
        copy_quality_issues=copy_quality_issues,
        claim_risks=claim_risks,
        conversions=conversions,
        match_findings=match_findings,
        font_measurements=font_measurements,
        barcode_results=barcode_results,
        snapshot_paths=snapshot_paths,
    )

    report_path = output_dir / "artwork_check_report.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info(f"Report saved: {report_path}")

    total = len(match_findings)
    exact = sum(1 for f in match_findings if f.match_type.value == "exact")
    if total > 0:
        logger.info(f"\nSUMMARY: {exact}/{total} exact matches ({exact/total*100:.1f}%)")
    else:
        logger.info("\nSUMMARY: No fields to check")

    return report, snapshot_paths


# ---------------------------------------------------------------------------
# Post-run output
# ---------------------------------------------------------------------------

def emit_report_and_snapshots(
    report: str,
    output_dir: Path,
    snapshot_paths: List[str],
) -> None:
    """
    Print the full markdown report then a deterministic snapshot section.

    Output is pure stdout markdown — no IPython / display() calls.
    Image paths are relative to output_dir so they resolve from the saved .md file.
    """
    output_dir = Path(output_dir)
    sep = "=" * 60

    # 1. Full report — never truncated
    print(f"\n{sep}")
    print("ARTWORK CHECK REPORT")
    print(f"{sep}\n")
    try:
        print(report)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(report.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")

    # 2. Snapshot section — explicit image tags, no UI assumptions
    print(f"\n{sep}")
    print("## Snapshots")
    print(f"{sep}\n")

    snap_dir = output_dir / "snapshots"
    # Use authoritative snapshot_paths when available; fall back to directory scan
    if snapshot_paths:
        png_paths = [Path(p) for p in snapshot_paths if Path(p).exists()]
    elif snap_dir.is_dir():
        png_paths = sorted(snap_dir.glob("*.png"))
    else:
        png_paths = []

    if not png_paths:
        print("| Status |")
        print("|--------|")
        print("| No snapshots generated |")
    else:
        for png in png_paths:
            try:
                rel = Path(png).relative_to(output_dir)
            except ValueError:
                rel = Path(png)  # absolute fallback if outside output_dir
            print(f"![{Path(png).name}]({rel.as_posix()})")
            print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Artwork Checker Pass 2 — v{config.VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Pass 2: validate overrides, apply, generate full report.
Requires Pass 1 artifacts (lock file, vision_tasks.json) to exist.

Example:
  python artwork_checker_pass2.py \\
    --copy copy.xlsx --artwork artwork.pdf --output ./output \\
    --vision-overrides ./output/vision_overrides.json
        """,
    )
    parser.add_argument("--copy", "-c", type=Path, required=True,
                        help="Path to copy document (.xlsx)")
    parser.add_argument("--artwork", "-a", type=Path, nargs="+", required=True,
                        help="Path to artwork file(s) (.pdf and/or .ai)")
    parser.add_argument("--output", "-o", type=Path, default=Path("./output"),
                        help="Output directory (default: ./output)")
    parser.add_argument("--vision-overrides", type=Path, required=True,
                        dest="vision_overrides",
                        metavar="PATH",
                        help="Path to completed vision_overrides.json (required)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging")
    parser.add_argument("--no-snapshots", action="store_true",
                        help="Disable snapshot generation")
    parser.add_argument("--version", action="version",
                        version=f"Artwork Checker Pass 2 v{config.VERSION}")
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    if args.no_snapshots:
        config.SNAPSHOT_ENABLED = False

    try:
        report, snapshot_paths = run_pass2(
            copy_path=args.copy,
            artwork_paths=args.artwork,
            output_dir=args.output,
            vision_overrides_path=args.vision_overrides,
            no_snapshots=args.no_snapshots,
        )

        emit_report_and_snapshots(report, args.output, snapshot_paths)
        sys.exit(0)

    except SystemExit:
        raise  # gate_check already printed errors and called sys.exit(1)

    except FileNotFoundError as e:
        print("\n=== PASS 2 ERROR ===", file=sys.stderr)
        print(f"ERROR TYPE: FileNotFoundError", file=sys.stderr)
        print(f"MESSAGE: {e}", file=sys.stderr)
        print("TRACEBACK:", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        print("====================", file=sys.stderr)
        sys.exit(1)

    except ValueError as e:
        print("\n=== PASS 2 ERROR ===", file=sys.stderr)
        print(f"ERROR TYPE: ValueError", file=sys.stderr)
        print(f"MESSAGE: {e}", file=sys.stderr)
        print("TRACEBACK:", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        print("====================", file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        print("\n=== PASS 2 ERROR ===", file=sys.stderr)
        print(f"ERROR TYPE: {type(e).__name__}", file=sys.stderr)
        print(f"MESSAGE: {e}", file=sys.stderr)
        print("TRACEBACK:", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        print("====================", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
