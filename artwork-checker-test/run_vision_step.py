#!/usr/bin/env python3
"""
run_vision_step.py — Display Pass 1 vision artifacts for GPT visual read.

Loads vision_tasks.json and vision_overrides.prefill.json from the Pass 1
output directory, displays all page images, contact sheets, and wide crops
inline (via IPython.display in Code Interpreter), and prints the item manifest.

The GPT must then:
  1. Read the displayed images visually.
  2. Write vision_overrides.json (modifying vision_overrides.prefill.json).
  3. Run validate_overrides_cli.py to confirm the file is valid.

Exits 0 on success (images displayed, ready for GPT to fill overrides).
Exits 1 on prerequisite failure (Pass 1 not run, artifacts missing).

Usage:
  python run_vision_step.py --output ./output
"""

import argparse
import json
import pathlib
import sys

try:
    from IPython.display import display as ipy_display, Image as IPImage
    HAS_IPYTHON = True
except ImportError:
    HAS_IPYTHON = False


def _show_image(path: str, label: str) -> None:
    """Display image inline (Code Interpreter) or print path (CLI)."""
    p = pathlib.Path(path)
    if not p.exists():
        print(f"  [IMAGE MISSING: {path}]")
        return
    print(f"\n[{label}]")
    if HAS_IPYTHON:
        ipy_display(IPImage(filename=str(p)))
    else:
        print(f"  image: {p}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Display vision artifacts for GPT visual verification"
    )
    parser.add_argument(
        "--output", default="./output",
        help="Output directory used in Pass 1 (default: ./output)"
    )
    args = parser.parse_args()

    output = pathlib.Path(args.output).resolve()
    sep = "=" * 60

    # ------------------------------------------------------------------
    # Prerequisite checks
    # ------------------------------------------------------------------
    done_path = output / ".PASS1_DONE"
    tasks_path = output / "gpt_vision" / "vision_tasks.json"
    prefill_path = output / "gpt_vision" / "vision_overrides.prefill.json"

    errors = []
    if not done_path.exists():
        errors.append("output/.PASS1_DONE not found — run RUN first.")
    if not tasks_path.exists():
        errors.append("output/gpt_vision/vision_tasks.json not found — run RUN first.")
    if not prefill_path.exists():
        errors.append(
            "output/gpt_vision/vision_overrides.prefill.json not found — run RUN first."
        )

    if errors:
        print(f"\n{sep}", file=sys.stderr)
        print("VISION STEP FAILED — prerequisites missing:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        print(f"\n{sep}", file=sys.stderr)
        print(f"\n{sep}")
        print("VISION STEP FAILED — run RUN before VISION.")
        print(sep)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Load artifacts
    # ------------------------------------------------------------------
    try:
        tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Cannot parse vision_tasks.json: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        prefill = json.loads(prefill_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Cannot parse vision_overrides.prefill.json: {e}", file=sys.stderr)
        sys.exit(1)

    items = tasks.get("items", [])
    page_images = tasks.get("page_images", {})
    contact_sheets = tasks.get("contact_sheets", [])
    task_hash = tasks.get("task_hash", "")
    human_token = prefill.get("vision_audit", {}).get("human_token", "")

    if not items:
        print(f"\n{sep}")
        print("VISION STEP — no items require visual verification.")
        print("All items were exact matches. Proceed directly to VALIDATE.")
        print(sep)
        print(
            f"VISION_STEP_READY: {json.dumps({'items': 0, 'task_hash': task_hash, 'output_dir': str(output)})}"
        )
        sys.exit(0)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print(f"VISION STEP — {len(items)} item(s) require visual verification")
    print(f"Task hash  : {task_hash[:16]}...")
    print(f"Human token: {human_token}")
    print(f"Output dir : {output}")
    print(sep)

    # ------------------------------------------------------------------
    # Full-page images (orientation)
    # ------------------------------------------------------------------
    print("\nFULL PAGE IMAGES — read holistically for layout orientation:")
    for page_num in sorted(page_images.keys(), key=lambda x: int(x)):
        path = page_images[page_num]
        _show_image(path, f"Page {page_num} — full artwork at 300 DPI")

    # ------------------------------------------------------------------
    # Contact sheets (labeled tiles — primary evidence source)
    # ------------------------------------------------------------------
    if contact_sheets:
        print(f"\n{'─' * 60}")
        print("CONTACT SHEETS — each tile labeled with its item ID:")
        for sheet in contact_sheets:
            ids_in_sheet = sheet.get("items", [])
            ids_preview = ", ".join(ids_in_sheet[:6])
            suffix = "…" if len(ids_in_sheet) > 6 else ""
            _show_image(
                sheet["sheet_path"],
                f"Sheet: {ids_preview}{suffix}"
            )
    else:
        print("\n[No contact sheets — use full page image to locate all items]")

    # ------------------------------------------------------------------
    # Wide crops (long / curved / risky text)
    # ------------------------------------------------------------------
    wide_items = [it for it in items if it.get("focus_crop_wide")]
    if wide_items:
        print(f"\n{'─' * 60}")
        print("WIDE CROPS — long / curved / risky text (read character-for-character):")
        for it in wide_items:
            _show_image(
                it["focus_crop_wide"],
                f"{it['id']} — wide crop ({it['field_name']})"
            )

    # ------------------------------------------------------------------
    # Item manifest
    # ------------------------------------------------------------------
    print(f"\n{'─' * 60}")
    print(f"ITEMS TO VERIFY ({len(items)} total):\n")
    for item in items:
        wide = item.get("focus_crop_wide")
        crop = item.get("focus_crop")
        if wide:
            evidence_label = "wide crop (displayed above)"
        elif crop:
            evidence_label = "tight crop (contact sheet tile)"
        else:
            evidence_label = "NOT FOUND — scan full page image"

        prefill_item = next(
            (o for o in prefill.get("overrides", []) if o.get("finding_id") == item["id"]),
            {}
        )
        default_found = prefill_item.get("found", False)
        default_value = prefill_item.get("visual_artwork_value", "")

        print(f"• [{item['id']}] {item['field_name']} | {item['panel']} | {item['language']}")
        print(f"  Copy doc value : {item['copy_value']}")
        print(f"  Script value   : {item['script_artwork_value']}  ({item['script_match_type']})")
        print(f"  Default found  : {default_found}  |  Default value: {repr(default_value)}")
        print(f"  Evidence       : {evidence_label}")
        if item.get("zoom_reasons"):
            print(f"  Flags          : {', '.join(item['zoom_reasons'])}")
        print()

    # ------------------------------------------------------------------
    # Instructions and file paths
    # ------------------------------------------------------------------
    overrides_out = output / "vision_overrides.json"
    print(sep)
    print("NEXT STEPS:")
    print(f"  1. Read images above (pages → contact sheets → wide crops)")
    print(f"  2. Modify prefill: {prefill_path}")
    print(f"     - Set confirmed=true for every item")
    print(f"     - FOUND: found=true, visual_artwork_value=<retype exactly as printed>")
    print(f"     - NOT FOUND (non-exact items): found=false, visual_artwork_value=\"\",")
    print(f"       reason_not_found=<one of: not_present_on_artwork | illegible |")
    print(f"       not_in_provided_crops | blocked_or_obscured | language_variant_mismatch>")
    print(f"       (reason_not_found required for all non-exact items — VISION gate will")
    print(f"        reject overrides without it)")
    print(f"  3. Write to   : {overrides_out}")
    print(f"  4. Validate   : python /mnt/data/validate_overrides_cli.py --output {output}")
    print(sep)

    # Machine-parseable footer — used by GPT instruction gate in Rule 5
    footer = {
        "status": "READY",
        "items": len(items),
        "task_hash": task_hash,
        "output_dir": str(output),
        "prefill_path": str(prefill_path),
        "overrides_out": str(overrides_out),
    }
    print(f"VISION_STEP_READY: {json.dumps(footer, ensure_ascii=False)}")

    sys.exit(0)


if __name__ == "__main__":
    main()
