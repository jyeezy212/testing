#!/usr/bin/env python3
"""
================================================================================
ARTWORK CHECKER — PASS 1
================================================================================
Responsibilities:
  1. Extract copy document (.xlsx)
  2. Extract artwork (.pdf / .ai)
  3. Copy quality analysis (Section A)
  4. Claim risk assessment (Section B)
  5. Conversion check + artwork matching (Sections C / D)
  6. Generate ALL vision artifacts (full-page images, crops, contact sheets,
     vision_tasks.json) — always runs when a PDF is present
  7. Generate vision_overrides.prefill.json
  8. Write output/.PASS1_DONE lock file
  9. Write output/.HUMAN_TOKEN (random 7-char token)
 10. Print HUMAN TOKEN instruction to stdout
 11. Print <<<GPT_VISION_REQUIRED>>> sentinel block
 12. Write output/.pass1_summary.json (machine-readable summary for wrapper)
 13. Exit 42 (PDF present, vision required) or 0 (no PDF)

HARD CONSTRAINTS:
  - NO --vision-overrides CLI argument
  - NEVER reads or applies vision_overrides.json
  - NEVER imports or calls VisionOverrideApplier, FontExtractor,
    BarcodeScanner, SnapshotGenerator, MarkdownRenderer
  - NEVER generates the final markdown verification report

USAGE:
  python artwork_checker_pass1.py --copy doc.xlsx --artwork art.pdf --output ./output
================================================================================
"""

import argparse
import json
import logging
import secrets
import string
import sys
import traceback
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Import ONLY Pass 1 classes from core (no Pass 2 classes imported)
# ---------------------------------------------------------------------------
from artwork_checker_core import (
    config,
    logger,
    ExcelCopyExtractor,
    PDFExtractor,
    AIExtractor,
    CopyQualityChecker,
    ClaimRiskAssessor,
    ConversionChecker,
    ArtworkMatcher,
    VisionExporter,
    ExtractionResult,
    ExtractionMethod,
    StatusCode,
    MatchFinding,
    MatchType,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PASS1_LOCK_FILE = ".PASS1_DONE"
HUMAN_TOKEN_FILE = ".HUMAN_TOKEN"
EXIT_VISION_REQUIRED = 42


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_dependencies() -> None:
    """Hard-fail with a clear error block if required third-party libraries are absent."""
    missing_libs = []
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        missing_libs.append("openpyxl")
    try:
        import fitz  # noqa: F401  (PyMuPDF)
    except ImportError:
        missing_libs.append("pymupdf")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing_libs.append("pillow")
    if missing_libs:
        print("\n=== PASS 1 DEPENDENCY ERROR ===", file=sys.stderr)
        print(f"ERROR TYPE: MissingDependency", file=sys.stderr)
        print(f"MESSAGE: Required libraries not installed: {', '.join(missing_libs)}", file=sys.stderr)
        print("Fix: pip install pymupdf openpyxl pillow pyzbar", file=sys.stderr)
        print("================================", file=sys.stderr)
        sys.exit(1)


def _atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write content atomically via a .tmp sibling, then rename, preventing partial reads."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding=encoding)
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _generate_human_token(length: int = 7) -> str:
    """Generate a random uppercase-alphanumeric token for human verification."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _extract_artwork(artwork_paths, pdf_extractor, ai_extractor):
    """Try PDF paths first, then AI, return (ExtractionResult, used_path).

    If any PDF is present it is always returned — even with confidence=0 (e.g. an
    image-only PDF) — so VisionExporter can render pages and generate vision artifacts
    regardless of text extraction quality.
    """
    pdf_paths = [p for p in artwork_paths if p.suffix.lower() == ".pdf"]
    ai_paths = [p for p in artwork_paths if p.suffix.lower() == ".ai"]

    first_pdf_result: Optional[tuple] = None
    for pdf_path in pdf_paths:
        extraction = pdf_extractor.extract(pdf_path)
        if first_pdf_result is None:
            first_pdf_result = (extraction, pdf_path)
        if extraction.confidence > 0:
            return extraction, pdf_path

    # PDF present but zero-confidence: still return it so vision artifacts are generated.
    if first_pdf_result is not None:
        return first_pdf_result

    for ai_path in ai_paths:
        extraction = ai_extractor.extract(ai_path)
        if extraction.confidence > 0:
            return extraction, ai_path

    # Fallback: failed extraction
    fallback_path = artwork_paths[0]
    return ExtractionResult(
        file_path=str(fallback_path),
        file_type=fallback_path.suffix.lower().lstrip("."),
        extraction_method=ExtractionMethod.FAILED,
        confidence=0.0,
        warnings=["All artwork extraction methods failed"],
    ), fallback_path


def _resolve_evidence_relative(path_str: str, output_dir: Path) -> str:
    """Return evidence path relative to output_dir for portable, consistent resolution."""
    if not path_str:
        return ""
    p = Path(path_str)
    try:
        return p.relative_to(output_dir).as_posix()
    except ValueError:
        return p.as_posix()


def _build_prefill(tasks_data: dict, human_token: str, output_dir: Path) -> dict:
    """
    Build vision_overrides.prefill.json from vision_tasks.json data.

    Default states per item:
      - Exact match  → found=True,  value pre-filled (human confirms visually).
      - Non-exact / NOT FOUND → found=False, value blank (human fills after visual read).

    Evidence paths are stored relative to output_dir so validation resolves them
    correctly regardless of the working directory when Pass 2 runs.
    """
    items = tasks_data.get("items", [])
    page_images = tasks_data.get("page_images", {})
    task_hash = tasks_data.get("task_hash", "")

    def _best_evidence(item):
        if item.get("focus_crop_wide"):
            return "focus_crop_wide", item["focus_crop_wide"]
        if item.get("focus_crop"):
            return "focus_crop", item["focus_crop"]
        return "page_image", page_images.get(str(item.get("page_guess", 1)), "")

    overrides = []
    for item in items:
        ev_type, ev_path = _best_evidence(item)
        is_exact = item.get("script_match_type") == "exact"
        is_not_found = (item.get("script_artwork_value") or "").upper() == "NOT FOUND"
        # found=True only for script-confirmed exact matches; everything else starts False
        # so the human must explicitly set found=True and supply a value after visual read.
        default_found = is_exact and not is_not_found
        entry = {
            "finding_id": item["id"],
            "visual_artwork_value": item.get("script_artwork_value", "") if default_found else "",
            "found": default_found,
            "confirmed": False,
            "evidence": ev_type,
            "evidence_path": _resolve_evidence_relative(ev_path, output_dir),
        }
        # Non-exact items must supply reason_not_found when found=false (Option A).
        # Pre-populate the field as empty so the reviewer knows it needs to be filled.
        if not default_found:
            entry["reason_not_found"] = ""
        overrides.append(entry)

    return {
        "vision_audit": {
            "source": "manual_image_read",
            "task_hash": task_hash,
            "human_token": human_token,
        },
        "overrides": overrides,
    }


# ---------------------------------------------------------------------------
# Pass 1 runner
# ---------------------------------------------------------------------------

def run_pass1(
    copy_path: Path,
    artwork_paths: List[Path],
    output_dir: Path,
) -> bool:
    """
    Execute Pass 1 pipeline.

    Returns True if vision artifacts were generated (exit 42 expected),
    False if no PDF was present (exit 0).
    """
    logger.info("=" * 60)
    logger.info(f"ARTWORK CHECKER PASS 1 — v{config.VERSION}")
    logger.info("=" * 60)

    copy_path = Path(copy_path)
    artwork_paths = [Path(p) for p in artwork_paths]
    output_dir = Path(output_dir)

    if not copy_path.exists():
        raise FileNotFoundError(f"Copy document not found: {copy_path.resolve()}")
    for ap in artwork_paths:
        if not ap.exists():
            raise FileNotFoundError(f"Artwork file not found: {ap.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 1: Extract copy document
    # ------------------------------------------------------------------
    logger.info("\n[1/5] Extracting copy document...")
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
    logger.info("\n[2/5] Extracting artwork...")
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
    logger.info("\n[3/5] Analyzing copy quality...")
    copy_quality_issues = CopyQualityChecker.analyze_copy_document(copy_doc)
    logger.info(f"  - Issues: {len(copy_quality_issues)}")

    # ------------------------------------------------------------------
    # Step 4: Claim risk (Section B)
    # ------------------------------------------------------------------
    logger.info("\n[4/5] Assessing claim risks...")
    claim_risks = ClaimRiskAssessor.assess_all_claims(copy_doc)
    logger.info(f"  - Claims: {len(claim_risks)}")

    # ------------------------------------------------------------------
    # Step 5: Conversions + matching (Sections C / D)
    # ------------------------------------------------------------------
    logger.info("\n[5/5] Running conversions and artwork matching...")
    conversions = ConversionChecker.check_conversions(copy_doc)
    matcher = ArtworkMatcher()
    match_findings = matcher.match_fields(
        copy_doc.fields,
        artwork_extraction.text_runs,
        artwork_extraction.extraction_method,
        copy_quality_issues,
    )

    # ------------------------------------------------------------------
    # Step 6: Vision artifacts (only when PDF present)
    # ------------------------------------------------------------------
    if not (artwork_path_used and artwork_path_used.suffix.lower() == ".pdf"):
        logger.warning(
            "Artwork is not a PDF — vision export skipped. "
            "Pass 2 requires vision artifacts and cannot run."
        )
        _atomic_write(output_dir / PASS1_LOCK_FILE, "PASS1_DONE_NO_PDF")
        print("\nPass 1 complete — no PDF provided; vision export skipped.")
        print("Pass 2 requires vision artifacts. Provide a PDF artwork file.")
        return False

    logger.info("\n[VISION] Exporting full-page images, crops, contact sheets...")
    vision_exporter = VisionExporter()
    tasks_path = vision_exporter.export(artwork_path_used, match_findings, output_dir)

    tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))
    tier1_count = sum(
        1 for f in match_findings
        if f.requires_zoom or f.status_code in (
            StatusCode.FAIL, StatusCode.ATTN, StatusCode.TBD
        )
    )

    # ------------------------------------------------------------------
    # Generate human token + write artifacts
    # ------------------------------------------------------------------
    human_token = _generate_human_token()

    # Write .HUMAN_TOKEN (atomic)
    _atomic_write(output_dir / HUMAN_TOKEN_FILE, human_token)
    logger.info(f"Human token written: {(output_dir / HUMAN_TOKEN_FILE).resolve()}")

    # Write prefill JSON (atomic)
    prefill = _build_prefill(tasks_data, human_token, output_dir)
    prefill_path = output_dir / "gpt_vision" / "vision_overrides.prefill.json"
    _atomic_write(prefill_path, json.dumps(prefill, indent=2, ensure_ascii=False))
    logger.info(f"Prefill written: {prefill_path.resolve()}")

    # Write machine-readable summary (atomic)
    summary = {
        "human_token": human_token,
        "task_hash": tasks_data.get("task_hash"),
        "item_count": len(tasks_data.get("items", [])),
        "vision_tasks": str(tasks_path),
        "prefill": str(prefill_path),
    }
    _atomic_write(output_dir / ".pass1_summary.json",
                  json.dumps(summary, indent=2, ensure_ascii=False))
    logger.info(f"Pass 1 summary written: {(output_dir / '.pass1_summary.json').resolve()}")

    # Write lock file (atomic) — intentionally LAST so the wrapper's artifact poll only
    # succeeds once every preceding file is already present on disk.
    _atomic_write(output_dir / PASS1_LOCK_FILE, "PASS1_DONE")
    logger.info(f"Lock file written: {(output_dir / PASS1_LOCK_FILE).resolve()}")

    # ------------------------------------------------------------------
    # Self-check: verify all artifacts are readable before signaling success
    # ------------------------------------------------------------------
    _required_artifacts = [
        output_dir / PASS1_LOCK_FILE,
        output_dir / HUMAN_TOKEN_FILE,
        tasks_path,
        prefill_path,
    ]
    _still_missing = [str(p.resolve()) for p in _required_artifacts if not p.exists()]
    if _still_missing:
        raise RuntimeError(
            "Pass 1 artifact self-check failed — files not found after write:\n"
            + "\n".join(f"  {p}" for p in _still_missing)
        )

    # ------------------------------------------------------------------
    # Print human token instruction (must be visible to human / GPT)
    # ------------------------------------------------------------------
    sep = "=" * 60
    print(f"\n{sep}")
    print("PASS 1 COMPLETE")
    print(sep)
    print(f"\nHUMAN TOKEN : {human_token}")
    print("\nThis token proves a human read the images.")
    print("Required steps:")
    print(f"  1. Open  : {prefill_path}")
    print(f"  2. Review each item visually using the images in {output_dir / 'gpt_vision'}")
    print( "  3. Set visual_artwork_value for each non-exact item")
    print( "  4. Set confirmed: true for every item")
    print(f"  5. vision_audit.human_token is pre-filled as '{human_token}' — do not change it")
    print(f"  6. Save as: {output_dir / 'vision_overrides.json'}")
    print(sep)

    # ------------------------------------------------------------------
    # Print sentinel block
    # ------------------------------------------------------------------
    VisionExporter.print_sentinel(tasks_path, tier1_count)

    logger.info(
        f"Pass 1 complete. {tier1_count} items require visual verification. "
        "Exiting with code 42."
    )
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Artwork Checker Pass 1 — v{config.VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Pass 1: extract, match, generate vision artifacts, write lock + token, exit 42.

Example:
  python artwork_checker_pass1.py --copy copy.xlsx --artwork artwork.pdf --output ./output
        """,
    )
    parser.add_argument("--copy", "-c", type=Path, required=True,
                        help="Path to copy document (.xlsx)")
    parser.add_argument("--artwork", "-a", type=Path, nargs="+", required=True,
                        help="Path to artwork file(s) (.pdf and/or .ai)")
    parser.add_argument("--output", "-o", type=Path, default=Path("./output"),
                        help="Output directory (default: ./output)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging")
    parser.add_argument("--version", action="version",
                        version=f"Artwork Checker Pass 1 v{config.VERSION}")
    return parser.parse_args()


def main() -> None:
    _check_dependencies()  # hard-fail early if pymupdf / openpyxl / pillow are missing

    args = parse_arguments()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        vision_required = run_pass1(
            copy_path=args.copy,
            artwork_paths=args.artwork,
            output_dir=args.output,
        )
        sys.exit(EXIT_VISION_REQUIRED if vision_required else 0)

    except FileNotFoundError as e:
        print("\n=== PASS 1 ERROR ===", file=sys.stderr)
        print(f"ERROR TYPE: FileNotFoundError", file=sys.stderr)
        print(f"MESSAGE: {e}", file=sys.stderr)
        print("TRACEBACK:", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        print("====================", file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        print("\n=== PASS 1 ERROR ===", file=sys.stderr)
        print(f"ERROR TYPE: {type(e).__name__}", file=sys.stderr)
        print(f"MESSAGE: {e}", file=sys.stderr)
        print("TRACEBACK:", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        print("====================", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
