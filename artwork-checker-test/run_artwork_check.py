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
    Display vision task images inline for the GPT visual pass.

    In Code Interpreter / Jupyter this renders the images directly in output.
    Outside IPython it prints file paths as a fallback.

    After calling this function the GPT must:
      1. Read the displayed images character-by-character
      2. Write ./output/vision_overrides.json with vision_audit stamp + evidence fields
      3. Call run_full_check() again with vision_overrides_path set
    """
    try:
        from IPython.display import display, Image as IPImage
        _has_ipython = True
    except ImportError:
        _has_ipython = False

    items = tasks.get("items", [])
    page_images = tasks.get("page_images", {})
    output_dir = tasks.get("output_dir", "./output")
    task_hash = tasks.get("task_hash", "")
    overrides_path = str(Path(output_dir) / "vision_overrides.json")

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"VISION PASS — {len(items)} item(s) require visual verification")
    print(sep)

    # Full-page image(s) first: holistic overview
    for page_num, path in page_images.items():
        print(f"\n[Page {page_num} — full artwork at 300 DPI — read holistically]")
        if _has_ipython:
            display(IPImage(filename=str(path)))
        else:
            print(f"  image: {path}")

    # Per-item detail
    print(f"\n{'─' * 60}")
    print("ITEMS TO VERIFY:")
    for item in items:
        print(f"\n• [{item['id']}] {item['field_name']}  |  {item['panel']}  |  {item['language']}")
        print(f"  Copy value  : {item['copy_value']}")
        print(f"  Script found: {item['script_artwork_value']}  ({item['script_match_type']})")
        if item.get("zoom_reasons"):
            print(f"  Zoom reasons: {', '.join(item['zoom_reasons'])}")

        focus = item.get("focus_crop")
        if focus:
            print(f"  [Focus crop — zoomed to matched text]")
            if _has_ipython:
                display(IPImage(filename=str(focus)))
            else:
                print(f"  focus: {focus}")
        else:
            print("  [NOT FOUND — scan the full page image above]")

    # Overrides template — pre-filled with required fields including audit stamp and evidence
    print(f"\n{sep}")
    print("NEXT STEP — read each image above; fill 'visual_artwork_value' from what you see — DO NOT copy script_artwork_value — then write:")
    print(f"  {overrides_path}")
    template = {
        "vision_audit": {
            "source": "manual_image_read",
            "task_hash": task_hash,
        },
        "overrides": [
            {
                "finding_id": item["id"],
                "visual_artwork_value": "",
                "found": True,
                "notes": (
                    f"Visually verified on page {item['page_guess']}, "
                    f"{item['panel']}, {item['language']}"
                ),
                "evidence": "focus_crop" if item.get("focus_crop") else "page_image",
                "evidence_path": item.get("focus_crop") or page_images.get(str(item.get("page_guess", 1)), ""),
            }
            for item in items
        ],
    }
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
