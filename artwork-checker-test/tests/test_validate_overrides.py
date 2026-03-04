"""
tests/test_validate_overrides.py

Tests for validate_overrides_cli.py — verifies the machine token output
for good, bad, and missing input files.

Note: these tests do NOT import artwork_checker_core directly; they invoke
validate_overrides_cli.py as a subprocess so the same code path is tested.

Updated to include all evidence-binding required fields:
  source_image, source_image_sha256, transcription_method, char_count,
  punctuation_signature, has_diacritics, nonce, generation_mode,
  generator_version, timestamp.
"""

import hashlib
import json
import string
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

REPO = Path(__file__).parent.parent
CLI = str(REPO / "validate_overrides_cli.py")

_TASK_HASH = "testhash123"
_TOKEN = "TESTTOKEN123"


# ---------------------------------------------------------------------------
# Pure helpers (mirror of production code — no imports from scripts)
# ---------------------------------------------------------------------------

def _nonce(fid: str, task_hash: str = _TASK_HASH) -> str:
    return hashlib.sha256(f"{task_hash}:{fid}:nonce_v1".encode()).hexdigest()[:12]


def _ps(value: str) -> list:
    return sorted(set(c for c in value if c in string.punctuation))


def _hd(value: str) -> bool:
    return any(
        unicodedata.category(c).startswith("L") and ord(c) > 127
        for c in value
    )


def _chash(overrides: list) -> str:
    """Mirror of validate_overrides_cli._content_hash() for anti-reuse tests."""
    items = sorted(
        (
            o.get("finding_id", ""),
            str(o.get("found")),
            o.get("visual_artwork_value", ""),
            o.get("reason_not_found", ""),
        )
        for o in overrides
    )
    return hashlib.sha256(
        json.dumps(items, sort_keys=True).encode()
    ).hexdigest()[:16]


# ---------------------------------------------------------------------------
# File-creation helpers
# ---------------------------------------------------------------------------

def _write_dummy_image(tmp_dir: Path, rel_path: str) -> str:
    """Write a dummy file (stable bytes) and return its SHA256."""
    p = tmp_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    content = b"DUMMY_IMAGE_" + rel_path.encode()
    p.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _make_vision_tasks(
    tmp_dir: Path,
    required_ids: list | None = None,
    task_items: list | None = None,
    task_hash: str = _TASK_HASH,
) -> Path:
    tasks = {
        "task_hash": task_hash,
        "required_ids": required_ids or [],
        "items": task_items if task_items is not None else [],
        "page_images": {},
        "contact_sheets": [],
    }
    gv = tmp_dir / "gpt_vision"
    gv.mkdir(parents=True, exist_ok=True)
    p = gv / "vision_tasks.json"
    p.write_text(json.dumps(tasks), encoding="utf-8")
    return p


def _make_human_token(tmp_dir: Path, token: str = _TOKEN) -> str:
    (tmp_dir / ".HUMAN_TOKEN").write_text(token, encoding="utf-8")
    return token


def _make_enriched_prefill(
    tmp_dir: Path,
    fids: list,
    task_hash: str = _TASK_HASH,
    token: str = _TOKEN,
    spotcheck_items: dict | None = None,
) -> Path:
    """
    Write enriched vision_overrides.prefill.json.
    spotcheck_items: {fid: {"type": ..., "instruction": ...}}
    """
    overrides = []
    for fid in fids:
        img_rel = f"gpt_vision/crops/{fid}_page_1.png"
        entry = {
            "finding_id": fid,
            "found": False,
            "visual_artwork_value": "",
            "confirmed": False,
            "recommended_source_image": img_rel,
            "alternate_images": [],
            "nonce": _nonce(fid, task_hash),
        }
        if spotcheck_items and fid in spotcheck_items:
            entry["spotcheck_challenge"] = spotcheck_items[fid]
        overrides.append(entry)
    data = {
        "vision_audit": {"human_token": token, "task_hash": task_hash},
        "overrides": overrides,
    }
    p = tmp_dir / "gpt_vision" / "vision_overrides.prefill.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _full_audit(
    token: str = _TOKEN,
    task_hash: str = _TASK_HASH,
    generation_mode: str = "interactive_ai",
    generator_version: str = "2.0.0",
    timestamp: str = "2026-03-04T12:00:00Z",
) -> dict:
    return {
        "human_token": token,
        "source": "manual_image_read",
        "task_hash": task_hash,
        "generation_mode": generation_mode,
        "generator_version": generator_version,
        "timestamp": timestamp,
    }


def _make_full_override_item(
    tmp_dir: Path,
    fid: str,
    found: bool,
    value: str = "",
    reason: str = "",
    task_hash: str = _TASK_HASH,
    img_rel: str | None = None,
) -> dict:
    """Build a complete override item with all required fields."""
    if img_rel is None:
        img_rel = f"gpt_vision/crops/{fid}_page_1.png"
    sha256 = _write_dummy_image(tmp_dir, img_rel)
    item: dict = {
        "finding_id": fid,
        "found": found,
        "visual_artwork_value": value,
        "confirmed": True,
        "evidence": "focus_crop",  # required by core validator
        "evidence_path": img_rel,  # required by core validator; file exists at tmp_dir/img_rel
        "source_image": img_rel,
        "source_image_sha256": sha256,
        "transcription_method": "model_retype",
        "char_count": len(value),
        "punctuation_signature": _ps(value),
        "has_diacritics": _hd(value),
        "nonce": _nonce(fid, task_hash),
    }
    if not found:
        item["reason_not_found"] = reason
    return item


def _make_overrides(
    tmp_dir: Path,
    token: str,
    overrides: list,
    task_hash: str = _TASK_HASH,
) -> Path:
    data = {
        "vision_audit": _full_audit(token, task_hash),
        "overrides": overrides,
    }
    p = tmp_dir / "vision_overrides.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _run_cli(output_dir: str, overrides_path: str | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, CLI, "--output", output_dir]
    if overrides_path:
        cmd += ["--overrides", overrides_path]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")


# ---------------------------------------------------------------------------
# Pass tests
# ---------------------------------------------------------------------------

class TestValidateOverridesPass(unittest.TestCase):

    def test_empty_overrides_pass(self):
        """items=0 + updated audit fields → VALIDATE_OVERRIDES_PASS."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=[])
            overrides = _make_overrides(tmp_path, token, overrides=[])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)

    def test_valid_found_false_items(self):
        """found=false items with all required fields → VALIDATE_OVERRIDES_PASS."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(
                tmp_path,
                required_ids=["D-001", "D-002"],
                task_items=[
                    {"id": "D-001", "script_match_type": "near"},
                    {"id": "D-002", "script_match_type": "near"},
                ],
            )
            _make_enriched_prefill(tmp_path, ["D-001", "D-002"])
            items = [
                _make_full_override_item(
                    tmp_path, "D-001", False, reason="not_present_on_artwork"
                ),
                _make_full_override_item(tmp_path, "D-002", False, reason="illegible"),
            ]
            overrides = _make_overrides(tmp_path, token, items)
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)
            # Verify .VISION_DONE was created
            self.assertTrue((tmp_path / ".VISION_DONE").exists())

    def test_valid_found_true_items(self):
        """found=true with non-empty value and self-consistency fields → PASS."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            _make_enriched_prefill(tmp_path, ["D-001"])
            items = [
                _make_full_override_item(tmp_path, "D-001", True, value="Exact Text"),
            ]
            overrides = _make_overrides(tmp_path, token, items)
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)

    def test_valid_found_true_with_punctuation(self):
        """found=true with punctuation/diacritics → char_count/signature computed correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            _make_enriched_prefill(tmp_path, ["D-001"])
            value = "Café, 250 ml."
            items = [_make_full_override_item(tmp_path, "D-001", True, value=value)]
            overrides = _make_overrides(tmp_path, token, items)
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)

    def test_pass_creates_vision_done(self):
        """validate success → .VISION_DONE exists in output dir."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=[])
            overrides = _make_overrides(tmp_path, token, overrides=[])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(
                (tmp_path / ".VISION_DONE").exists(),
                ".VISION_DONE should be created on pass",
            )

    def test_pass_token_json_keys_sorted(self):
        """VALIDATE_OVERRIDES_PASS JSON keys must be sorted."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path)
            overrides = _make_overrides(tmp_path, token, overrides=[])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0)
            for line in proc.stdout.splitlines():
                if line.startswith("VALIDATE_OVERRIDES_PASS:"):
                    keys = list(json.loads(line[len("VALIDATE_OVERRIDES_PASS:"):].strip()).keys())
                    self.assertEqual(keys, sorted(keys))
                    break


# ---------------------------------------------------------------------------
# Basic structural fail tests
# ---------------------------------------------------------------------------

class TestValidateOverridesFail(unittest.TestCase):

    def test_confirmed_false_gives_fail(self):
        """confirmed=false → VALIDATE_OVERRIDES_FAIL in stderr."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            item = _make_full_override_item(
                tmp_path, "D-001", False, reason="not_present_on_artwork"
            )
            item["confirmed"] = False  # intentional fault
            overrides = _make_overrides(tmp_path, token, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)

    def test_found_true_empty_value_gives_fail(self):
        """found=true with empty value → VALIDATE_OVERRIDES_FAIL."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            item = _make_full_override_item(tmp_path, "D-001", True, value="placeholder")
            item["visual_artwork_value"] = ""  # intentional fault
            overrides = _make_overrides(tmp_path, token, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)

    def test_token_mismatch_gives_fail(self):
        """Wrong human_token → structural validation fails."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path, token="CORRECT_TOKEN")
            _make_vision_tasks(tmp_path)
            overrides = _make_overrides(tmp_path, "WRONG_TOKEN", overrides=[])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)


# ---------------------------------------------------------------------------
# File-not-found tests
# ---------------------------------------------------------------------------

class TestValidateOverridesFileNotFound(unittest.TestCase):

    def test_missing_overrides_file_exits2(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run_cli(tmp, str(Path(tmp) / "nonexistent.json"))
            self.assertEqual(proc.returncode, 2)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)

    def test_missing_vision_tasks_exits2(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            overrides = _make_overrides(tmp_path, "TOKEN", overrides=[])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 2)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)


# ---------------------------------------------------------------------------
# Audit metadata enforcement
# ---------------------------------------------------------------------------

class TestAuditMetadataEnforcement(unittest.TestCase):

    def _make_empty_overrides_with_audit(self, tmp_path, audit_override):
        _make_human_token(tmp_path)
        _make_vision_tasks(tmp_path, required_ids=[])
        audit = _full_audit()
        audit.update(audit_override)
        data = {"vision_audit": audit, "overrides": []}
        p = tmp_path / "vision_overrides.json"
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return p

    def test_missing_generation_mode_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            overrides = self._make_empty_overrides_with_audit(
                tmp_path, {"generation_mode": ""}
            )
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("generation_mode", proc.stderr)

    def test_missing_generator_version_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            overrides = self._make_empty_overrides_with_audit(
                tmp_path, {"generator_version": ""}
            )
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("generator_version", proc.stderr)

    def test_missing_timestamp_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            overrides = self._make_empty_overrides_with_audit(
                tmp_path, {"timestamp": ""}
            )
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("timestamp", proc.stderr)


# ---------------------------------------------------------------------------
# Evidence binding enforcement
# ---------------------------------------------------------------------------

class TestEvidenceBinding(unittest.TestCase):

    def test_missing_source_image_fails(self):
        """source_image absent → VALIDATE_OVERRIDES_FAIL."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            item = _make_full_override_item(
                tmp_path, "D-001", False, reason="illegible"
            )
            item["source_image"] = ""  # intentional fault
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("source_image", proc.stderr)

    def test_source_image_file_missing_fails(self):
        """source_image points to non-existent file → FAIL."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            item = _make_full_override_item(
                tmp_path, "D-001", False, reason="illegible"
            )
            item["source_image"] = "gpt_vision/crops/D-001_nonexistent.png"
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)

    def test_wrong_sha256_fails(self):
        """source_image_sha256 doesn't match file → FAIL."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            item = _make_full_override_item(
                tmp_path, "D-001", False, reason="illegible"
            )
            item["source_image_sha256"] = "a" * 64  # wrong hash
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("sha256", proc.stderr.lower())

    def test_missing_sha256_fails(self):
        """source_image_sha256 absent → FAIL (use build_overrides_from_ai_response.py)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            item = _make_full_override_item(
                tmp_path, "D-001", False, reason="illegible"
            )
            item["source_image_sha256"] = ""  # intentional fault
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)

    def test_source_image_not_in_allowed_fails(self):
        """source_image not in enriched prefill allowed list → FAIL."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            _make_enriched_prefill(tmp_path, ["D-001"])
            # Use a different image path — still create the file so it exists
            wrong_img = "gpt_vision/crops/D-001_wrong_image.png"
            wrong_sha = _write_dummy_image(tmp_path, wrong_img)
            item = _make_full_override_item(tmp_path, "D-001", False, reason="illegible")
            item["source_image"] = wrong_img
            item["source_image_sha256"] = wrong_sha
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)
            self.assertIn("allowed", proc.stderr)

    def test_missing_transcription_method_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            item = _make_full_override_item(tmp_path, "D-001", False, reason="illegible")
            item["transcription_method"] = ""  # intentional fault
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("transcription_method", proc.stderr)

    def test_invalid_transcription_method_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            item = _make_full_override_item(tmp_path, "D-001", False, reason="illegible")
            item["transcription_method"] = "ocr_auto"  # not allowed
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("transcription_method", proc.stderr)


# ---------------------------------------------------------------------------
# Self-consistency enforcement
# ---------------------------------------------------------------------------

class TestSelfConsistency(unittest.TestCase):

    def test_wrong_char_count_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            _make_enriched_prefill(tmp_path, ["D-001"])
            item = _make_full_override_item(tmp_path, "D-001", True, value="hello")
            item["char_count"] = 99  # wrong
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("char_count", proc.stderr)

    def test_wrong_punctuation_signature_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            _make_enriched_prefill(tmp_path, ["D-001"])
            item = _make_full_override_item(tmp_path, "D-001", True, value="hello")
            item["punctuation_signature"] = ["!"]  # wrong
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("punctuation_signature", proc.stderr)

    def test_wrong_has_diacritics_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            _make_enriched_prefill(tmp_path, ["D-001"])
            item = _make_full_override_item(tmp_path, "D-001", True, value="hello")
            item["has_diacritics"] = True  # wrong — "hello" has no diacritics
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("has_diacritics", proc.stderr)


# ---------------------------------------------------------------------------
# Nonce enforcement
# ---------------------------------------------------------------------------

class TestNonceEnforcement(unittest.TestCase):

    def test_missing_nonce_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            _make_enriched_prefill(tmp_path, ["D-001"])
            item = _make_full_override_item(tmp_path, "D-001", False, reason="illegible")
            item["nonce"] = ""  # intentional fault
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("nonce", proc.stderr)

    def test_wrong_nonce_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            _make_enriched_prefill(tmp_path, ["D-001"])
            item = _make_full_override_item(tmp_path, "D-001", False, reason="illegible")
            item["nonce"] = "wrongnonce00"  # different from _nonce("D-001")
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("nonce", proc.stderr)

    def test_correct_nonce_passes(self):
        """Correct nonce matches prefill → no nonce error."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"],
                               task_items=[{"id": "D-001", "script_match_type": "near"}])
            _make_enriched_prefill(tmp_path, ["D-001"])
            item = _make_full_override_item(tmp_path, "D-001", False, reason="illegible")
            # nonce already set correctly by _make_full_override_item
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)


# ---------------------------------------------------------------------------
# Spotcheck enforcement
# ---------------------------------------------------------------------------

class TestSpotcheckEnforcement(unittest.TestCase):

    def _setup_with_spotcheck(self, tmp_path, fid, value, challenge_type="char_count"):
        _make_human_token(tmp_path)
        _make_vision_tasks(
            tmp_path,
            required_ids=[fid],
            task_items=[{"id": fid, "script_match_type": "near"}],
        )
        challenge = {
            "type": challenge_type,
            "instruction": f"Test challenge: {challenge_type}",
        }
        _make_enriched_prefill(tmp_path, [fid], spotcheck_items={fid: challenge})
        item = _make_full_override_item(tmp_path, fid, True, value=value)
        return item, challenge

    def test_missing_spotcheck_answer_fails(self):
        """Item with spotcheck_challenge but no spotcheck_answer → FAIL."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            item, _ = self._setup_with_spotcheck(tmp_path, "D-001", "hello world")
            # Don't add spotcheck_answer
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("spotcheck_answer", proc.stderr)

    def test_wrong_spotcheck_answer_fails(self):
        """Spotcheck answer inconsistent with value → FAIL."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            value = "hello world"
            item, _ = self._setup_with_spotcheck(tmp_path, "D-001", value, "char_count")
            item["spotcheck_answer"] = "999"  # wrong — len("hello world") = 11
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)

    def test_correct_spotcheck_char_count_passes(self):
        """Correct char_count spotcheck answer → PASS."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            value = "hello world"
            item, _ = self._setup_with_spotcheck(tmp_path, "D-001", value, "char_count")
            item["spotcheck_answer"] = str(len(value))  # correct
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)

    def test_correct_spotcheck_first_3_chars_passes(self):
        """Correct first_3_chars spotcheck → PASS."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            value = "Amika Body Wash"
            item, _ = self._setup_with_spotcheck(tmp_path, "D-001", value, "first_3_chars")
            item["spotcheck_answer"] = value[:3]
            overrides = _make_overrides(tmp_path, _TOKEN, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)


# ---------------------------------------------------------------------------
# Anti-reuse enforcement
# ---------------------------------------------------------------------------

class TestAntiReuse(unittest.TestCase):

    def test_same_values_different_task_hash_fails(self):
        """Same override content hash for a different task_hash → FAIL."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=[])
            overrides_list = []
            overrides = _make_overrides(tmp_path, _TOKEN, overrides_list)

            # Pre-populate the reuse guard: another task used the exact same content
            chash = _chash(overrides_list)
            guard_path = tmp_path / ".vision_reuse_guard.json"
            guard_path.write_text(
                json.dumps({"other_task_hash_xyz": chash}), encoding="utf-8"
            )

            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("Anti-reuse", proc.stderr)

    def test_same_task_hash_same_values_passes(self):
        """Re-running validate for same task_hash + same content → PASS (retry is OK)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=[])
            overrides_list = []
            overrides = _make_overrides(tmp_path, _TOKEN, overrides_list)

            # Pre-populate guard with SAME task_hash + same content
            chash = _chash(overrides_list)
            guard_path = tmp_path / ".vision_reuse_guard.json"
            guard_path.write_text(
                json.dumps({_TASK_HASH: chash}), encoding="utf-8"
            )

            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)

    def test_pass_updates_reuse_guard(self):
        """Successful validation updates .vision_reuse_guard.json."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=[])
            overrides = _make_overrides(tmp_path, _TOKEN, overrides=[])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0)
            guard_path = tmp_path / ".vision_reuse_guard.json"
            self.assertTrue(guard_path.exists())
            guard = json.loads(guard_path.read_text())
            self.assertIn(_TASK_HASH, guard)


# ---------------------------------------------------------------------------
# Option A enforcement (unchanged logic, updated fixtures)
# ---------------------------------------------------------------------------

class TestOptionAEnforcement(unittest.TestCase):

    def _non_exact_tasks(self, tmp_path: Path, fid: str = "D-001") -> None:
        _make_vision_tasks(
            tmp_path,
            required_ids=[fid],
            task_items=[{"id": fid, "script_match_type": "near"}],
        )

    def test_non_exact_found_false_no_reason_gives_fail(self):
        """Non-exact item, found=false, no reason_not_found → FAIL."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            self._non_exact_tasks(tmp_path)
            item = _make_full_override_item(tmp_path, "D-001", False, reason="")
            # Remove reason_not_found entirely
            item.pop("reason_not_found", None)
            overrides = _make_overrides(tmp_path, token, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)
            self.assertIn("reason_not_found", proc.stderr)

    def test_non_exact_found_false_invalid_reason_gives_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            self._non_exact_tasks(tmp_path)
            item = _make_full_override_item(
                tmp_path, "D-001", False, reason="just_didnt_look"
            )
            overrides = _make_overrides(tmp_path, token, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)

    def test_non_exact_found_false_valid_reason_passes(self):
        """Non-exact item, found=false, valid reason → PASS."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            self._non_exact_tasks(tmp_path)
            item = _make_full_override_item(
                tmp_path, "D-001", False, reason="not_present_on_artwork"
            )
            overrides = _make_overrides(tmp_path, token, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)

    def test_all_valid_reasons_accepted(self):
        for reason in [
            "not_present_on_artwork", "illegible", "not_in_provided_crops",
            "blocked_or_obscured", "language_variant_mismatch",
        ]:
            with self.subTest(reason=reason):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    token = _make_human_token(tmp_path)
                    self._non_exact_tasks(tmp_path)
                    item = _make_full_override_item(
                        tmp_path, "D-001", False, reason=reason
                    )
                    overrides = _make_overrides(tmp_path, token, [item])
                    proc = _run_cli(tmp, str(overrides))
                    self.assertEqual(
                        proc.returncode, 0,
                        f"reason={reason} stderr: {proc.stderr}",
                    )
                    self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)

    def test_exact_item_found_false_no_reason_passes(self):
        """Exact-match item found=false needs no reason_not_found."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(
                tmp_path,
                required_ids=["D-001"],
                task_items=[{"id": "D-001", "script_match_type": "exact"}],
            )
            item = _make_full_override_item(tmp_path, "D-001", False, reason="")
            item.pop("reason_not_found", None)  # no reason needed for exact items
            overrides = _make_overrides(tmp_path, token, [item])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
