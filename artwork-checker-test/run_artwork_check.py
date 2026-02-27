"""
run_artwork_check.py — Single-response orchestrator for artwork_checker_v2_1_xlsx.py

In Code Interpreter / GPT context, import this module and use the Python API:

    from run_artwork_check import run_full_check, display_vision_tasks

    report, tasks = run_full_check("doc.xlsx", ["art.pdf"], "./output")
    if tasks:
        display_vision_tasks(tasks)   # images appear inline; GPT reads them
        # GPT writes ./output/vision_overrides.json (including vision_audit + evidence fields), then:
        report, _ = run_full_check("doc.xlsx", ["art.pdf"], "./output",
                                   vision_overrides_path="./output/vision_overrides.json")
    print(report)

As CLI:
    python run_artwork_check.py --copy doc.xlsx --artwork art.pdf --output ./output
    python run_artwork_check.py --copy doc.xlsx --artwork art.pdf --output ./output \
        --vision-overrides ./output/vision_overrides.json
"""

import sys
import json
import argparse
import importlib.util
from pathlib import Path


# ---------------------------------------------------------------------------
# Dynamic import of the checker (works whether run from script dir or CWD)
# ---------------------------------------------------------------------------

def _load_checker_module():
    candidates = [
        Path(__file__).parent / "artwork_checker_v2_1_xlsx.py",
        Path.cwd() / "artwork_checker_v2_1_xlsx.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("artwork_checker", str(candidate))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError(
        "artwork_checker_v2_1_xlsx.py not found. "
        "Place it in the same directory as run_artwork_check.py or in CWD."
    )


_checker_mod = None


def _get_checker_mod():
    global _checker_mod
    if _checker_mod is None:
        _checker_mod = _load_checker_module()
    return _checker_mod


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _load_vision_tasks_manifest(output_dir):
    """Load Pass 1 vision task manifest (vision_tasks.json) if it exists."""
    tasks_path = Path(output_dir) / "gpt_vision" / "vision_tasks.json"
    if not tasks_path.exists():
        return None
    return json.loads(tasks_path.read_text(encoding="utf-8"))


def validate_vision_overrides(output_dir, vision_overrides_path):
    """
    Orchestrator-side guardrail: refuse Pass 2 unless overrides contain a valid
    vision_audit stamp, matching task_hash, per-item evidence, and are not
    mass-identical to script extraction.

    Raises ValueError if validation fails.
    """
    tasks = _load_vision_tasks_manifest(output_dir)
    if tasks is None:
        raise FileNotFoundError(
            f"vision_tasks.json not found under {Path(output_dir) / 'gpt_vision' / 'vision_tasks.json'}. "
            "Run Pass 1 first to generate vision tasks."
        )

    ov_path = Path(vision_overrides_path)
    raw = json.loads(ov_path.read_text(encoding="utf-8"))

    # Require audit stamp and task hash match
    audit = raw.get("vision_audit")
    if not isinstance(audit, dict) or audit.get("source") != "manual_image_read":
        raise ValueError(
            "VISION OVERRIDE REJECTED: Missing/invalid vision_audit stamp "
            "(source must be 'manual_image_read')."
        )
    task_hash = tasks.get("task_hash")
    if task_hash and audit.get("task_hash") != task_hash:
        raise ValueError(
            "VISION OVERRIDE REJECTED: task_hash mismatch vs current vision_tasks.json."
        )

    overrides = raw.get("overrides", [])
    if not isinstance(overrides, list) or not overrides:
        raise ValueError("VISION OVERRIDE REJECTED: overrides list missing/empty.")

    required_ids = set(tasks.get("required_ids", []))
    seen = [o.get("finding_id") for o in overrides]
    if len(seen) != len(set(seen)):
        raise ValueError("VISION OVERRIDE REJECTED: duplicate finding_id in overrides.")
    missing = required_ids - set(seen)
    extra = set(seen) - required_ids
    if missing:
        raise ValueError(f"VISION OVERRIDE REJECTED: missing required IDs: {sorted(missing)[:10]}")
    if extra:
        raise ValueError(f"VISION OVERRIDE REJECTED: unknown IDs present: {sorted(extra)[:10]}")

    # Evidence required + no empty found=true values
    for o in overrides:
        fid = o.get("finding_id", "")
        found = bool(o.get("found", False))
        v = (o.get("visual_artwork_value") or "").strip()
        ev = (o.get("evidence") or "").strip()
        evp = (o.get("evidence_path") or "").strip()
        if found and not v:
            raise ValueError(
                f"VISION OVERRIDE REJECTED: {fid} found=true but visual_artwork_value empty."
            )
        if not (ev or evp):
            raise ValueError(
                f"VISION OVERRIDE REJECTED: {fid} missing evidence/evidence_path."
            )
        # Validate evidence_path actually exists on disk (within expected output dir)
        if evp:
            evp_path = Path(evp)
            if not evp_path.is_absolute():
                evp_path = Path(tasks.get("output_dir", ".")) / evp_path
            if not evp_path.exists():
                raise ValueError(
                    f"VISION OVERRIDE REJECTED: {fid} evidence_path does not exist: {evp}"
                )

    # Note: identical-rate check removed — audit stamp + evidence fields are
    # the authoritative gate; confirmed-correct values will legitimately match.


def run_full_check(copy_path, artwork_paths, output_dir="./output",
                   vision_overrides_path=None):
    """
    Run the full artwork check workflow.

    Parameters
    ----------
    copy_path : str | Path
        Path to the .xlsx copy document.
    artwork_paths : str | Path | list
        Path(s) to the artwork PDF/AI file(s).
    output_dir : str | Path
        Directory for output files (default: ./output).
    vision_overrides_path : str | Path | None
        Pass 2: path to vision_overrides.json written by the GPT visual pass.
        Leave None for Pass 1.

    Returns
    -------
    (report: str | None, tasks: dict | None)
        Pass 1 with vision required  → (None, tasks_dict)
        Pass 2 / no vision needed    → (report_str, None)
    """
    mod = _get_checker_mod()
    ArtworkChecker = mod.ArtworkChecker
    VisionPassRequired = mod.VisionPassRequired

    if isinstance(artwork_paths, (str, Path)):
        artwork_paths = [artwork_paths]

    checker = ArtworkChecker()
    try:
        # Orchestrator-side safety gate: refuse to proceed with Pass 2 unless
        # vision_overrides.json matches the current Pass 1 manifest and includes evidence.
        if vision_overrides_path is not None:
            validate_vision_overrides(output_dir, vision_overrides_path)

        report = checker.run_check(
            copy_path=str(copy_path),
            artwork_paths=[str(p) for p in artwork_paths],
            output_dir=str(output_dir),
            vision_overrides_path=str(vision_overrides_path) if vision_overrides_path else None,
        )
        return report, None

    except VisionPassRequired as e:
        tasks = json.loads(Path(e.tasks_path).read_text(encoding="utf-8"))
        return None, tasks


def display_vision_tasks(tasks):
    """
    Display vision evidence for the GPT visual pass.

    Shows only: full page image(s) + contact sheet(s) (typically 2–8 images
    total), then a text-only item list and the overrides template.  Individual
    focus crop files are NOT displayed inline — the contact sheets contain all
    tight crops at 1:1 scale, each labeled with its item ID.

    After calling this function the GPT must:
      1. Read the displayed images (page overview + contact sheets)
      2. Write ./output/vision_overrides.json with vision_audit stamp + evidence
      3. Call run_full_check() again with vision_overrides_path set
    """
    try:
        from IPython.display import display, Image as IPImage
        _has_ipython = True
    except ImportError:
        _has_ipython = False

    def _show_image(path, label):
        print(f"\n[{label}]")
        if _has_ipython:
            display(IPImage(filename=str(path)))
        else:
            print(f"  image: {path}")

    items = tasks.get("items", [])
    page_images = tasks.get("page_images", {})
    contact_sheets = tasks.get("contact_sheets", [])
    output_dir = tasks.get("output_dir", "./output")
    task_hash = tasks.get("task_hash", "")
    overrides_path = str(Path(output_dir) / "vision_overrides.json")

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"VISION PASS — {len(items)} item(s) require visual verification")
    print(f"Contact sheets: {len(contact_sheets)}  |  Display images: "
          f"{len(page_images) + len(contact_sheets)}")
    print(sep)

    # --- Full page image(s): holistic orientation ---
    for page_num, path in page_images.items():
        _show_image(path, f"Page {page_num} — full artwork at 300 DPI — read holistically")

    # --- Contact sheets: all tight crops at 1:1, labeled with ID ---
    if contact_sheets:
        print(f"\n{'─' * 60}")
        print("CONTACT SHEETS — each tile is labeled with its item ID")
        for sheet in contact_sheets:
            ids_preview = ", ".join(sheet.get("items", [])[:6])
            suffix = "…" if len(sheet.get("items", [])) > 6 else ""
            _show_image(
                sheet["sheet_path"],
                f"Sheet: {ids_preview}{suffix}"
            )
    else:
        print("\n[No contact sheets generated — scan full page image above for all items]")

    # --- Text-only item list (no per-item image rendering) ---
    print(f"\n{'─' * 60}")
    print("ITEMS TO VERIFY (read from contact sheet tiles or wide crops below):\n")
    for item in items:
        wide = item.get("focus_crop_wide")
        evidence_label = "wide crop" if wide else ("tight crop" if item.get("focus_crop") else "NOT FOUND — scan full page")
        print(f"• [{item['id']}] {item['field_name']} | {item['panel']} | {item['language']}")
        print(f"  Copy     : {item['copy_value']}")
        print(f"  Script   : {item['script_artwork_value']}  ({item['script_match_type']})")
        print(f"  Evidence : {evidence_label}")
        if item.get("zoom_reasons"):
            print(f"  Flags    : {', '.join(item['zoom_reasons'])}")
        # Display wide crops inline individually (fewer in number, high priority)
        if wide:
            _show_image(wide, f"{item['id']} — wide crop (long/curved/risky text)")
        print()

    # --- Overrides template: evidence_path prefers wide > tight > page ---
    print(f"\n{sep}")
    print("NEXT STEP — read each image; fill 'visual_artwork_value' from what you "
          "see — DO NOT copy script_artwork_value — then write:")
    print(f"  {overrides_path}")

    def _best_evidence(item):
        if item.get("focus_crop_wide"):
            return "focus_crop_wide", item["focus_crop_wide"]
        if item.get("focus_crop"):
            return "focus_crop", item["focus_crop"]
        return "page_image", page_images.get(str(item.get("page_guess", 1)), "")

    template = {
        "vision_audit": {
            "source": "manual_image_read",
            "task_hash": task_hash,
        },
        "overrides": [],
    }
    for item in items:
        ev_type, ev_path = _best_evidence(item)
        template["overrides"].append({
            "finding_id": item["id"],
            "visual_artwork_value": "",
            "found": True,
            "notes": (
                f"Visually verified on page {item['page_guess']}, "
                f"{item['panel']}, {item['language']}"
            ),
            "evidence": ev_type,
            "evidence_path": ev_path,
        })
    print(json.dumps(template, indent=2, ensure_ascii=False))
    print(sep)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Artwork Checker — full workflow orchestrator"
    )
    parser.add_argument("--copy", required=True, help="Path to .xlsx copy document")
    parser.add_argument("--artwork", required=True, nargs="+", help="Path(s) to artwork PDF/AI")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument(
        "--vision-overrides", dest="vision_overrides",
        help="Pass 2: path to vision_overrides.json",
    )
    args = parser.parse_args()

    report, tasks = run_full_check(
        copy_path=args.copy,
        artwork_paths=args.artwork,
        output_dir=args.output,
        vision_overrides_path=args.vision_overrides,
    )

    if report:
        # Encode-safe print for Windows consoles
        try:
            print(report)
        except UnicodeEncodeError:
            sys.stdout.buffer.write(report.encode("utf-8", errors="replace"))
            sys.stdout.buffer.write(b"\n")
        sys.exit(0)

    # Vision pass needed
    display_vision_tasks(tasks)
    sys.exit(42)  # Distinct exit code: vision overrides required


if __name__ == "__main__":
    main()
