# Artwork Checker — Pass 1 / Pass 2 Refactor Plan

## Goal

Split `artwork_checker_v2_1_xlsx.py` (single monolithic orchestrator) into two separate
entry-point scripts with a hard structural gate between them.

---

## Files to Create / Modify

| File | Action | Purpose |
|---|---|---|
| `artwork_checker_core.py` | **Create** | All shared classes, enums, config, extractors, matchers, renderers — extracted from the monolith |
| `artwork_checker_pass1.py` | **Create** | Pass 1 entry point — extract, match, export vision artifacts, write lock file, exit 42 |
| `artwork_checker_pass2.py` | **Create** | Pass 2 entry point — gate check, validate overrides, apply, font/barcode/snapshots, report |
| `GPT_INSTRUCTIONS_XLSX.md` | **Update** | Add `artwork_checker_core.py` to Setup file list |
| `artwork_checker_v2_1_xlsx.py` | **Unchanged** | Existing monolith stays intact; backward compatibility preserved |
| `run_artwork_check.py` | **Unchanged** | Still works as before against the monolith |

---

## What Code Moves Where

### `artwork_checker_core.py` (lines 1–~3365 of monolith, minus CLI)

Everything except `parse_arguments()` and `main()`:

- All imports and logging setup
- Custom exceptions: `VisionPassRequired`, `VisionOverrideRejected`
- All enums: `ExtractionMethod`, `MatchType`, `StatusCode`, `RiskLevel`
- `Config`, all constants, `config` singleton
- All dataclasses: `TextRun`, `CopyField`, `MatchFinding`, `CopyQualityIssue`, `ClaimRisk`, `ConversionCheck`, `FontMeasurement`, `BarcodeResult`, `SnapshotAnnotation`, `ExtractionResult`, `CopyDocument`
- Utilities: `fuzzy_ratio`, `sanitize_for_markdown`, `truncate_text`
- Analysis helpers: `TextNormalizer`, `ZoomTriggerDetector`, `ExclusionChecker`, `InstructionalNoteDetector`, `CurvedTextDetector`, `INCIValidator`
- Extractors: `ExcelCopyExtractor`, `PDFExtractor`, `AIExtractor`
- Analysis: `CopyQualityChecker`, `ClaimRiskAssessor`, `ConversionChecker`
- Matching: `ArtworkMatcher`
- Vision (Pass 1): `VisionExporter`
- Vision (Pass 2 only): `VisionOverrideApplier`
- Report (Pass 2 only): `FontExtractor`, `BarcodeScanner`, `SnapshotGenerator`, `MarkdownRenderer`
- Shared validation: `validate_vision_overrides()` (moved from `run_artwork_check.py`)

> The monolithic `ArtworkChecker` class is **not** carried into core — it is replaced by
> the two separate runners below.

---

### `artwork_checker_pass1.py`

**Imports from core:** `ExcelCopyExtractor`, `PDFExtractor`, `AIExtractor`,
`CopyQualityChecker`, `ClaimRiskAssessor`, `ConversionChecker`, `ArtworkMatcher`,
`VisionExporter`, `ExtractionResult`, `ExtractionMethod`, `StatusCode`

**Does NOT import / call:** `VisionOverrideApplier`, `FontExtractor`, `BarcodeScanner`,
`SnapshotGenerator`, `MarkdownRenderer`

**Orchestration steps:**

```
1. Extract copy document        (ExcelCopyExtractor)
2. Extract artwork              (PDFExtractor → AIExtractor fallback)
3. Copy quality — Section A     (CopyQualityChecker)
4. Claim risks — Section B      (ClaimRiskAssessor)
5. Conversions + matching       (ConversionChecker, ArtworkMatcher)
6. Vision export — always       (VisionExporter.export())
   - Full-page images at 300 DPI
   - Focus crops + contact sheets
   - vision_tasks.json
7. Print sentinel block         (VisionExporter.print_sentinel())
8. Write lock file              output/.PASS1_DONE
9. Exit 42                      (vision required)
   Exit 0                       (no PDF — vision skipped, partial run noted)
```

**Hard constraints:**
- No `--vision-overrides` CLI argument
- No reading or applying `vision_overrides.json`
- No final markdown report generation
- Vision export always runs when a PDF is present (not gated on tier1 count)

**CLI:**
```
python artwork_checker_pass1.py --copy doc.xlsx --artwork art.pdf --output ./output
```

**Exit codes:**
- `42` — Pass 1 complete, vision verification required
- `0`  — Pass 1 complete, no PDF provided (vision skipped)
- `1`  — Error

---

### `artwork_checker_pass2.py`

**Imports from core:** everything — all Pass 1 classes plus `VisionOverrideApplier`,
`FontExtractor`, `BarcodeScanner`, `SnapshotGenerator`, `MarkdownRenderer`,
`validate_vision_overrides`

**Orchestration steps:**

```
GATE (fail-fast before any work):
  - output/.PASS1_DONE must exist
  - output/gpt_vision/vision_tasks.json must exist
  - --vision-overrides file must exist and pass structural validation:
      • vision_audit.source == "manual_image_read"
      • task_hash matches vision_tasks.json
      • all required IDs present, no duplicates, no extras
      • each override has confirmed: true
      • evidence paths exist on disk

1. Extract copy document        (same as Pass 1)
2. Extract artwork              (same as Pass 1)
3. Copy quality — Section A     (same as Pass 1)
4. Claim risks — Section B      (same as Pass 1)
5. Conversions + matching       (same as Pass 1 — rebuilds state in memory)
6. Apply vision overrides       (VisionOverrideApplier)
7. Font extraction — Section E  (FontExtractor)
8. Barcode scan — Section F     (BarcodeScanner)
9. Snapshots — Section G        (SnapshotGenerator)
10. Generate full report        (MarkdownRenderer)
11. Save report                 output/artwork_check_report.md
12. Print report
13. Exit 0
```

> Pass 2 re-extracts and re-matches from scratch to rebuild `match_findings` in memory.
> This avoids the need to serialize/deserialize intermediate state from Pass 1.

**CLI:**
```
python artwork_checker_pass2.py \
  --copy doc.xlsx \
  --artwork art.pdf \
  --output ./output \
  --vision-overrides ./output/vision_overrides.json
```

**Exit codes:**
- `0`  — Report generated successfully
- `1`  — Gate failed or any error

---

## `GPT_INSTRUCTIONS_XLSX.md` Changes

Only the **Setup section** changes. Add `artwork_checker_core.py` to the list of files
the GPT must write to `/mnt/data/` before running:

```
# Before
2. From Knowledge, open `artwork_checker_v2_1_xlsx.py` → write full contents to /mnt/data/
3. From Knowledge, open `run_artwork_check.py`          → write full contents to /mnt/data/

# After
2. From Knowledge, open `artwork_checker_core.py`       → write full contents to /mnt/data/
3. From Knowledge, open `artwork_checker_v2_1_xlsx.py`  → write full contents to /mnt/data/
4. From Knowledge, open `run_artwork_check.py`          → write full contents to /mnt/data/
```

All Python code blocks (Pass 1 / Pass 2 calls via `run_full_check`) are **unchanged** —
the public API of `run_artwork_check.py` is identical.

`VISION_INSTRUCTIONS.md` is auto-generated by `VisionExporter` — no manual update needed.

---

## CLI Workflow After Refactor

```bash
# Pass 1 — extract, match, export vision artifacts
python artwork_checker_pass1.py \
  --copy "amika Product_-_Bottle.xlsx" \
  --artwork "amika Product_-_Bottle.pdf" \
  --output ./output
# → exits 42
# → writes output/.PASS1_DONE
# → writes output/gpt_vision/vision_tasks.json
# → writes output/gpt_vision/vision_overrides.prefill.json
# → prints <<<GPT_VISION_REQUIRED>>>...<<<END_GPT_VISION_REQUIRED>>>

# → Human / GPT fills out vision_overrides.prefill.json
# → saves as output/vision_overrides.json (confirmed: true on all items)

# Pass 2 — validate overrides, apply, generate report
python artwork_checker_pass2.py \
  --copy "amika Product_-_Bottle.xlsx" \
  --artwork "amika Product_-_Bottle.pdf" \
  --output ./output \
  --vision-overrides ./output/vision_overrides.json
# → exits 0
# → writes output/artwork_check_report.md
# → prints full markdown report
```

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Core is a copy, not a refactor of the monolith | `artwork_checker_v2_1_xlsx.py` stays 100% untouched — zero regression risk |
| Pass 2 re-extracts from scratch | Avoids serializing `match_findings`; keeps logic simple and identical to Pass 1 |
| `validate_vision_overrides()` moves to core | Both `artwork_checker_pass2.py` and `run_artwork_check.py` import from one place |
| Lock file is `output/.PASS1_DONE` | Hidden dot-file; written by Pass 1, checked by Pass 2 before any work begins |
| Pass 1 exit code 42 | Distinct from 0 (success) and 1 (error); signals "vision required" to calling scripts |
| Pass 1 never imports Pass 2-only classes | Structural guarantee: `VisionOverrideApplier`, `FontExtractor`, `BarcodeScanner`, `SnapshotGenerator`, `MarkdownRenderer` absent from pass1.py imports |
