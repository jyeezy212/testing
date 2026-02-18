#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-file validator + deterministic table-only renderer for the Artwork Review SOP.

Dependencies:
  pip install jsonschema

Usage:
  python V2.py --in payload.json --out report.md
  # Optional: export the embedded schema for editing
  python V2.py --dump-schema sop.artwork-review.schema.json
  # Show CLI help
  python V2.py --help
"""

# =============================================================================
# Imports & constants
# =============================================================================
import argparse, json, sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

# Try to import PyMuPDF for font extraction
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False


# =============================================================================
# FONT EXTRACTION DATA MODELS & FUNCTIONS
# =============================================================================

@dataclass
class FontMeasurement:
    """Represents a font measurement from the artwork"""
    text: str
    page_number: int
    font_name: str
    font_size_pt: float
    bbox: Optional[Tuple[float, float, float, float]] = None


def extract_font_sizes_from_pdf(pdf_path: Path) -> List[FontMeasurement]:
    """
    Extract all font size measurements from a PDF file.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        List of FontMeasurement objects, one per text span
        
    Example:
        measurements = extract_font_sizes_from_pdf(Path("artwork.pdf"))
        smallest = get_smallest_font(measurements)
        print(f"Smallest font: {smallest.font_size_pt}pt")
    """
    if not PYMUPDF_AVAILABLE:
        print("ERROR: PyMuPDF required. Install: pip install PyMuPDF", file=sys.stderr)
        return []
    
    measurements = []
    
    try:
        doc = fitz.open(pdf_path)
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_measurements = _extract_page_fonts(page, page_num + 1)
            measurements.extend(page_measurements)
        
        doc.close()
        
    except Exception as e:
        print(f"ERROR: Failed to extract fonts from {pdf_path}: {e}", file=sys.stderr)
        return []
    
    return measurements


def _extract_page_fonts(page, page_num: int) -> List[FontMeasurement]:
    """
    Extract font measurements from a single PDF page.
    
    KEY FUNCTION: Uses PyMuPDF's page.get_text("dict") with flags=11 
    to extract text with font metadata.
    
    Args:
        page: PyMuPDF page object
        page_num: Page number (1-indexed)
        
    Returns:
        List of FontMeasurement objects from this page
    """
    measurements = []
    
    try:
        # Extract text with detailed metadata (flags=11 includes fonts)
        blocks = page.get_text("dict", flags=11)["blocks"]
        
        for block in blocks:
            if block.get("type") != 0:  # Skip non-text blocks
                continue
            
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    
                    if not text:
                        continue
                    
                    # KEY LINE: Extract font size metadata
                    font_name = span.get("font", "Unknown")
                    font_size = span.get("size", 0.0)  # Size in points
                    bbox = span.get("bbox")  # Bounding box
                    
                    if font_size > 0:
                        measurement = FontMeasurement(
                            text=text,
                            page_number=page_num,
                            font_name=font_name,
                            font_size_pt=round(font_size, 2),
                            bbox=tuple(bbox) if bbox else None
                        )
                        measurements.append(measurement)
                        
    except Exception as e:
        print(f"Warning: Error on page {page_num}: {e}", file=sys.stderr)
    
    return measurements


def get_smallest_font(measurements: List[FontMeasurement]) -> Optional[FontMeasurement]:
    """Find the smallest font in the measurements."""
    if not measurements:
        return None
    return min(measurements, key=lambda m: m.font_size_pt)


def check_font_compliance(smallest_font: FontMeasurement, region: str = "USA") -> Dict:
    """
    Check if font size meets regulatory requirements.
    
    Args:
        smallest_font: The smallest font measurement found
        region: Region code (USA, EU, UK)
        
    Returns:
        Dictionary with compliance status
    """
    requirements = {
        "USA": {"general": 4.5},
        "EU": {"general": 6.0},
        "UK": {"general": 6.0}
    }
    
    min_required = requirements.get(region, {}).get("general", 6.0)
    found_size = smallest_font.font_size_pt
    compliant = found_size >= min_required
    
    return {
        "region": region,
        "required_pt": min_required,
        "found_pt": found_size,
        "compliant": compliant,
        "status": "OK" if compliant else "FAIL",
        "text_sample": smallest_font.text[:50],
        "page": smallest_font.page_number,
        "font_name": smallest_font.font_name
    }


def print_font_report(measurements: List[FontMeasurement], regions: List[str] = ["USA"]):
    """Print a formatted report of font measurements."""
    if not measurements:
        print("No font measurements found.")
        return
    
    smallest = get_smallest_font(measurements)
    
    print("\n" + "="*60)
    print("FONT SIZE REPORT")
    print("="*60)
    print(f"Total text spans: {len(measurements)}")
    print(f"\nSmallest Font:")
    print(f"  Size: {smallest.font_size_pt} pt")
    print(f"  Font: {smallest.font_name}")
    print(f"  Page: {smallest.page_number}")
    print(f"  Text: \"{smallest.text[:50]}...\"")
    
    print(f"\nCompliance:")
    for region in regions:
        comp = check_font_compliance(smallest, region)
        print(f"  {region}: {comp['status']} (min: {comp['required_pt']}pt)")
    print("="*60 + "\n")


# =============================================================================
# SCHEMA (embedded JSON Schema — intentionally kept in-file for KB consistency)
# =============================================================================
SCHEMA_JSON = r"""
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/sop.artwork-review.schema.json",
  "title": "Artwork Review SOP",
  "type": "object",
  "additionalProperties": false,
  "required": ["step1", "step2", "step3", "step4", "step5"],
  "properties": {
    "version": {
      "type": "string",
      "description": "Schema/user payload version (semantic version preferred)",
      "pattern": "^\\d+\\.\\d+\\.\\d+$"
    },

    "step1": {
      "title": "Project Header",
      "type": "object",
      "additionalProperties": false,
      "required": ["project_name", "round_version", "regions_in_scope", "due_date"],
      "properties": {
        "project_name": { "type": "string", "minLength": 1 },
        "round_version": { "type": "string", "minLength": 1 },
      }
    },

    "step2": {
      "title": "Files to Attach",
      "type": "object",
      "additionalProperties": false,
      "required": ["files"],
      "properties": {
        "files": {
          "type": "array",
          "items": { "$ref": "#/$defs/fileItem" },
          "minItems": 2
        }
      },
      "allOf": [
        {
          "contains": {
            "type": "object",
            "required": ["type"],
            "properties": { "type": { "const": "Copy Document" } }
          }
        },
        {
          "contains": {
            "type": "object",
            "required": ["type"],
            "properties": { "type": { "const": "Artwork" } }
          }
        }
      ]
    },

    "step3": {
      "title": "Core Verification Tables (A–H)",
      "type": "object",
      "additionalProperties": false,
      "required": [
        "copy_quality",
        "claim_risk",
        "label_claim_conversion",
        "artwork_match",
        "font_size",
        "barcode",
        "visual_snapshots",
        "score_summary"
      ],
      "properties": {
        "copy_quality": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["language", "original_text", "recommendation", "status_code", "evidence"],
            "properties": {
              "language": { "$ref": "#/$defs/languageEnum" },
              "original_text": { "type": "string" },
              "recommendation": { "type": "string" },
              "status_code": { "$ref": "#/$defs/statusEnum" },
              "evidence": { "type": "string" }
            }
          }
        },

        "claim_risk": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["language", "claim", "risk_level", "rationale", "regions_impacted", "action", "status_code"],
            "properties": {
              "language": { "$ref": "#/$defs/languageEnum" },
              "claim": { "type": "string" },
              "risk_level": { "$ref": "#/$defs/riskLevelEnum" },
              "rationale": { "type": "string" },
              "regions_impacted": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": true,
                "items": { "$ref": "#/$defs/regionEnum" }
              },
              "action": { "$ref": "#/$defs/actionEnum" },
              "status_code": { "$ref": "#/$defs/statusEnum" }
            }
          }
        },

        "label_claim_conversion": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["source", "declared_ml", "calculated_fl_oz", "declared_fl_oz", "within_tolerance", "status_code", "notes"],
            "properties": {
              "source": { "type": "string", "minLength": 1 },
              "declared_ml": { "type": "number", "minimum": 0 },
              "calculated_fl_oz": { "type": "number", "minimum": 0 },
              "declared_fl_oz": { "type": "number", "minimum": 0 },
              "within_tolerance": { "type": "boolean" },
              "status_code": { "$ref": "#/$defs/statusEnum" },
              "notes": { "type": "string" }
            }
          }
        },

        "artwork_match": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["field", "copy_doc_value", "artwork_value", "match", "notes"],
            "properties": {
              "field": { "type": "string" },
              "copy_doc_value": { "type": "string" },
              "artwork_value": { "type": "string" },
              "match": { "type": "boolean" },
              "notes": { "type": "string" }
            }
          }
        },

        "font_size": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["text", "jurisdiction", "required_min_pt", "measured_min_pt", "method", "status_code", "screenshot_id"],
            "properties": {
              "text": { "type": "string" },
              "jurisdiction": { "type": "string" },
              "required_min_pt": { "type": "number", "minimum": 0 },
              "measured_min_pt": { "type": "number", "minimum": 0 },
              "method": { "$ref": "#/$defs/methodEnum" },
              "status_code": { "$ref": "#/$defs/statusEnum" },
              "screenshot_id": { "type": "string" }
            }
          }
        },

        "barcode": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["symbology", "encoded_digits", "check_digit_valid", "x_dim_mm", "quiet_zone_mm", "module_count", "print_contrast", "scan_test"],
            "properties": {
              "symbology": { "$ref": "#/$defs/symbologyEnum" },
              "encoded_digits": { "type": "string", "pattern": "^[0-9X]+$" },
              "check_digit_valid": { "type": "boolean" },
              "x_dim_mm": { "type": "number", "minimum": 0 },
              "quiet_zone_mm": { "type": "number", "minimum": 0 },
              "module_count": { "type": "integer", "minimum": 0 },
              "print_contrast": { "type": "number", "minimum": 0, "maximum": 100 },
              "scan_test": { "type": "string", "enum": ["Pass", "Fail", "N/A"] }
            }
          }
        },

        "visual_snapshots": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["id", "what", "where", "fix", "linked_rows", "status_after_fix"],
            "properties": {
              "id": { "type": "string", "pattern": "^G-\\d{3}$" },
              "what": { "type": "string" },
              "where": { "type": "string" },
              "fix": { "type": "string" },
              "linked_rows": { "type": "array", "items": { "type": "string" } },
              "status_after_fix": { "type": "string", "enum": ["TBD", "Resolved", "Rejected"] }
            }
          }
        },

        "score_summary": {
          "type": "object",
          "additionalProperties": false,
          "required": ["summary_rows", "top_fixes", "attention", "next_steps"],
          "properties": {
            "summary_rows": {
              "type": "array",
              "items": {
                "type": "object",
                "additionalProperties": false,
                "required": ["area", "checks", "matches", "score_percent", "notes"],
                "properties": {
                  "area": { "type": "string" },
                  "checks": { "type": "integer", "minimum": 0 },
                  "matches": { "type": "integer", "minimum": 0 },
                  "score_percent": { "type": "number", "minimum": 0, "maximum": 100 },
                  "notes": { "type": "string" }
                }
              }
            },
            "top_fixes": { "type": "array", "items": { "type": "string" } },
            "attention": { "type": "array", "items": { "type": "string" } },
            "next_steps": { "type": "array", "items": { "type": "string" } }
          }
        }
      }
    },

    "step4": {
      "title": "Optional Fields",
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "version_change_log": { "type": "string" },
        "creative_brand_voice_check": { "type": "string" },
        "one_page_pdf_summary_export": { "type": "boolean" }
      }
    },

    "step5": {
      "title": "Special Notes / Constraints",
      "type": "object",
      "additionalProperties": false,
      "required": ["constraints"],
      "properties": {
        "constraints": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["constraint", "source", "applies_to", "notes"],
            "properties": {
              "constraint": { "type": "string" },
              "source": {
                "type": "string",
                "enum": ["Retailer", "Regulatory", "Brand", "Legal", "Other"]
              },
              "applies_to": { "type": "string" },
              "notes": { "type": "string" }
            }
          }
        }
      }
    }
  },

  "$defs": {
    "regionEnum": {
      "type": "string",
      "enum": ["USA", "EU", "UK", "CA", "AU", "Other"]
    },
    "languageEnum": {
      "type": "string",
      "enum": ["EN", "FR", "ES", "DE", "IT", "PT", "NL", "Other"]
    },
    "statusEnum": {
      "type": "string",
      "enum": ["OK", "ATTN", "FAIL", "TBD", "FYI"]
    },
    "riskLevelEnum": {
      "type": "string",
      "enum": ["Low", "Medium", "High", "Prohibited"]
    },
    "actionEnum": {
      "type": "string",
      "enum": ["Keep", "Modify", "Remove", "Escalate"]
    },
    "methodEnum": {
      "type": "string",
      "enum": ["Bitmap", "Vector", "OCR", "Manual"]
    },
    "symbologyEnum": {
      "type": "string",
      "enum": ["UPC-A", "EAN-13", "Code128", "QR", "DataMatrix", "Other"]
    },
    "fileItem": {
      "type": "object",
      "additionalProperties": false,
      "required": ["type", "filename", "status_code"],
      "properties": {
        "type": { "type": "string", "enum": ["Copy Document", "Artwork", "Other"] },
        "filename": { "type": "string", "minLength": 1 },
        "status_code": { "$ref": "#/$defs/statusEnum" },
        "note": { "type": "string" }
      }
    }
  }
}
"""

# =============================================================================
# VALIDATION (schema loading + payload validation helpers)
# =============================================================================
def _require_jsonschema():
    try:
        from jsonschema import Draft202012Validator  # noqa: F401
    except Exception as e:
        print("ERROR: jsonschema is required. Install with: pip install jsonschema", file=sys.stderr)
        raise

def validate_payload(payload: dict):
    from jsonschema import Draft202012Validator
    schema = json.loads(SCHEMA_JSON)
    v = Draft202012Validator(schema)
    errors = sorted(v.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        msgs = []
        for e in errors:
            path = "/".join(map(str, e.path)) or "<root>"
            msgs.append(f"{path}: {e.message}")
        raise ValueError("Invalid SOP payload:\n" + "\n".join(msgs))
    return payload

# =============================================================================
# RENDERERS (deterministic, table-only Markdown rendering by SOP step)
# =============================================================================
def _format_regions(regions):
    # Flags removed — just join region labels
    return ", ".join(regions or [])

STATUS_EMOJI = {
    "OK": "✅",
    "ATTN": "⚠️",
    "FAIL": "❌",
    "TBD": "TBD",
    "FYI": "FYI"
}

def _print_table(header, rows):
    out = []
    out.append(header)
    out.append("")
    out.append("| " + " | ".join(rows[0]) + " |")
    out.append("|" + "|".join(["---"] * len(rows[0])) + "|")
    for r in rows[1:]:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)

def render_step1(d):
    rows = [
        ["Field", "Fill In"],
        ["Project Name", d["project_name"]],
        ["Round / Version", d["round_version"]],
    ]
    return _print_table("1️⃣ Project Header", rows)

def render_step2(d):
    rows = [["Type", "Filename", "Status", "Note"]]
    for f in d["files"]:
        rows.append([f["type"], f["filename"], STATUS_EMOJI[f["status_code"]], f.get("note","")])
    return _print_table("2️⃣ Files to Attach", rows)

def render_step3_copy_quality(items):
    rows = [["Language", "Original Text", "Recommendation", "Status", "Evidence"]]
    for x in items:
        rows.append([x["language"], x["original_text"], x["recommendation"], STATUS_EMOJI[x["status_code"]], x["evidence"]])
    return _print_table("A. Copy Quality", rows)

def render_step3_claim_risk(items):
    rows = [["Language", "Claim (quote)", "Risk Level", "Rationale", "Regions", "Action", "Status"]]
    for x in items:
        rows.append([x["language"], x["claim"], x["risk_level"], x["rationale"],
                     ", ".join(x["regions_impacted"]), x["action"], STATUS_EMOJI[x["status_code"]]])
    return _print_table("B. Claim Risk", rows)

def render_step3_label_claim_conversion(items):
    rows = [["Source", "Declared (mL)", "Calculated (fl oz)", "Declared (fl oz)", "Within ±0.10", "Status", "Notes"]]
    for x in items:
        rows.append([x["source"], x["declared_ml"], x["calculated_fl_oz"], x["declared_fl_oz"],
                     "Yes" if x["within_tolerance"] else "No", STATUS_EMOJI[x["status_code"]], x["notes"]])
    return _print_table("C. Label-Claim Conversion", rows)

def render_step3_artwork_match(items):
    rows = [["Field", "Copy Doc Value", "Artwork Value", "Match", "Notes"]]
    for x in items:
        rows.append([x["field"], x["copy_doc_value"], x["artwork_value"], "✅" if x["match"] else "❌", x["notes"]])
    return _print_table("D. Artwork Match", rows)

def render_step3_font_size(items):
    rows = [["Text String / Field", "Jurisdiction", "Required Min (pt)", "Measured Min (pt)", "Method", "Status", "Screenshot ID"]]
    for x in items:
        rows.append([x["text"], x["jurisdiction"], x["required_min_pt"], x["measured_min_pt"],
                     x["method"], STATUS_EMOJI[x["status_code"]], x["screenshot_id"]])
    return _print_table("E. Font Size", rows)

def render_step3_barcode(items):
    rows = [["Symbology", "Encoded Digits", "Check Digit Valid", "X-Dim (mm)", "Quiet Zone (mm)", "Module Count", "Print Contrast", "Scan Test"]]
    for x in items:
        rows.append([x["symbology"], x["encoded_digits"], "Yes" if x["check_digit_valid"] else "No",
                     x["x_dim_mm"], x["quiet_zone_mm"], x["module_count"], x["print_contrast"], x["scan_test"]])
    return _print_table("F. Barcode", rows)

def render_step3_visual_snapshots(items):
    rows = [["ID", "What", "Where", "Fix", "Linked Rows", "Status After Fix"]]
    for x in items:
        rows.append([x["id"], x["what"], x["where"], x["fix"], ", ".join(x["linked_rows"]), x["status_after_fix"]])
    return _print_table("G. Visual Snapshots", rows)

def render_step3_score_summary(d):
    rows = [["Area", "Checks", "Matches", "Score %", "Notes"]]
    for x in d["summary_rows"]:
        rows.append([x["area"], x["checks"], x["matches"], x["score_percent"], x["notes"]])
    block = _print_table("H. Score & Summary", rows)

    def small_table(title, items):
        rows = [["Item"]]
        for it in items:
            rows.append([it])
        return _print_table(title, rows)

    pieces = [block]
    pieces.append(small_table("Top Fixes (❌)", d.get("top_fixes", [])))
    pieces.append(small_table("Attention (⚠️)", d.get("attention", [])))
    pieces.append(small_table("Next Steps", d.get("next_steps", [])))
    return "\n\n".join(pieces)

def render_step3(d):
  parts = []
  parts.append(render_step3_copy_quality(d["copy_quality"]))
  parts.append(render_step3_claim_risk(d["claim_risk"]))
  parts.append(render_step3_label_claim_conversion(d["label_claim_conversion"]))
  parts.append(render_step3_artwork_match(d["artwork_match"]))
  parts.append(render_step3_font_size(d["font_size"]))
  parts.append(render_step3_barcode(d["barcode"]))
  parts.append(render_step3_visual_snapshots(d["visual_snapshots"]))
  parts.append(render_step3_score_summary(d["score_summary"]))
  header = "3️⃣ Core Verification Tables"
  return header + "\n\n" + "\n\n".join(parts)

def render_step4(d):
    rows = [["Field", "Content"]]
    if "version_change_log" in d: rows.append(["Version-Change Log", d["version_change_log"]])
    if "creative_brand_voice_check" in d: rows.append(["Creative Brand-Voice Check", d["creative_brand_voice_check"]])
    if "one_page_pdf_summary_export" in d: rows.append(["One-Page PDF Summary Export", "Yes" if d["one_page_pdf_summary_export"] else "No"])
    return _print_table("4️⃣ Optional Fields", rows)

def render_step5(d):
    rows = [["Constraint", "Source", "Applies To (Region/Panel)", "Notes"]]
    for x in d["constraints"]:
        rows.append([x["constraint"], x["source"], x["applies_to"], x["notes"]])
    return _print_table("5️⃣ Special Notes / Constraints", rows)

# =============================================================================
# CLI (argument parsing, file IO, orchestration, exit codes)
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="SOP validator + renderer (single-file).")
    parser.add_argument("--in", dest="inp", type=Path, help="Input payload JSON")
    parser.add_argument("--out", dest="out", type=Path, help="Output Markdown file")
    parser.add_argument("--dump-schema", dest="dump_schema", type=Path, help="Write embedded schema to this path and exit")
    parser.add_argument("--extract-fonts", dest="extract_fonts", type=Path, help="Extract font sizes from PDF and print report")
    args = parser.parse_args()

    if args.dump_schema:
        args.dump_schema.write_text(SCHEMA_JSON.strip() + "\n", encoding="utf-8")
        print(f"Wrote schema to {args.dump_schema}")
        return
    
    # NEW: Font extraction mode
    if args.extract_fonts:
        measurements = extract_font_sizes_from_pdf(args.extract_fonts)
        print_font_report(measurements, regions=["USA", "EU", "UK"])
        return

    try:
        from jsonschema import Draft202012Validator  # trigger helpful error if missing
    except Exception:
        print("ERROR: jsonschema is required. Install with: pip install jsonschema", file=sys.stderr)
        sys.exit(1)

    if not args.inp:
        print("ERROR: --in payload.json is required (or use --dump-schema).", file=sys.stderr)
        sys.exit(2)

    try:
        payload = json.loads(args.inp.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Failed to read JSON payload: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        validate_payload(payload)
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    out_parts = []
    out_parts.append(render_step1(payload["step1"]))
    out_parts.append(render_step2(payload["step2"]))
    out_parts.append(render_step3(payload["step3"]))
    if "step4" in payload:
        out_parts.append(render_step4(payload["step4"]))
    out_parts.append(render_step5(payload["step5"]))
    md = "\n\n".join(out_parts) + "\n"

    if args.out:
        args.out.write_text(md, encoding="utf-8")
        print(f"Wrote report to {args.out}")
    else:
        sys.stdout.write(md)

if __name__ == "__main__":
    main()