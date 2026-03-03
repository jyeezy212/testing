"""
tests/test_validate_overrides.py

Tests for validate_overrides_cli.py — verifies the machine token output
for good, bad, and missing input files.

Note: these tests do NOT import artwork_checker_core directly; they invoke
validate_overrides_cli.py as a subprocess so the same code path is tested.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).parent.parent
CLI = str(REPO / "validate_overrides_cli.py")


def _make_vision_tasks(tmp_dir: Path, required_ids: list[str] | None = None) -> Path:
    tasks = {
        "task_hash": "testhash123",
        "required_ids": required_ids or [],
        "items": [],
        "page_images": {},
        "contact_sheets": [],
    }
    gv = tmp_dir / "gpt_vision"
    gv.mkdir(parents=True, exist_ok=True)
    p = gv / "vision_tasks.json"
    p.write_text(json.dumps(tasks), encoding="utf-8")
    return p


def _make_human_token(tmp_dir: Path, token: str = "TESTTOKEN123") -> str:
    (tmp_dir / ".HUMAN_TOKEN").write_text(token, encoding="utf-8")
    return token


def _make_overrides(tmp_dir: Path, token: str, overrides: list) -> Path:
    data = {
        "vision_audit": {
            "human_token": token,
            "source": "manual_image_read",
            "task_hash": "testhash123",
        },
        "overrides": overrides,
    }
    p = tmp_dir / "vision_overrides.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _run_cli(output_dir: str, overrides_path: str | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, CLI, "--output", output_dir]
    if overrides_path:
        cmd += ["--overrides", overrides_path]
    return subprocess.run(cmd, capture_output=True, text=True)


class TestValidateOverridesPass(unittest.TestCase):

    def test_empty_overrides_pass(self):
        """items=0: empty overrides + empty required_ids → VALIDATE_OVERRIDES_PASS."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=[])
            overrides = _make_overrides(tmp_path, token, overrides=[])
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)

    def test_valid_overrides_with_items(self):
        """Valid overrides with found=false items → VALIDATE_OVERRIDES_PASS."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001", "D-002"])
            items = [
                {"finding_id": "D-001", "found": False, "visual_artwork_value": "",
                 "confirmed": True, "evidence": "contact sheet tile"},
                {"finding_id": "D-002", "found": False, "visual_artwork_value": "",
                 "confirmed": True, "evidence": "contact sheet tile"},
            ]
            overrides = _make_overrides(tmp_path, token, overrides=items)
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)
            # Verify token JSON has expected fields
            for line in proc.stdout.splitlines():
                if line.startswith("VALIDATE_OVERRIDES_PASS:"):
                    data = json.loads(line[len("VALIDATE_OVERRIDES_PASS:"):].strip())
                    self.assertIn("items_total", data)
                    self.assertIn("confirmed", data)
                    self.assertIn("found_true", data)
                    self.assertEqual(data["items_total"], 2)
                    break

    def test_valid_overrides_found_true(self):
        """found=true + non-empty value → VALIDATE_OVERRIDES_PASS."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            items = [
                {"finding_id": "D-001", "found": True, "visual_artwork_value": "Exact Text",
                 "confirmed": True, "evidence": "wide crop image"},
            ]
            overrides = _make_overrides(tmp_path, token, overrides=items)
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 0)
            self.assertIn("VALIDATE_OVERRIDES_PASS:", proc.stdout)


class TestValidateOverridesFail(unittest.TestCase):

    def test_confirmed_false_gives_fail(self):
        """confirmed=false → VALIDATE_OVERRIDES_FAIL in stderr."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            items = [
                {"finding_id": "D-001", "found": False, "visual_artwork_value": "",
                 "confirmed": False, "evidence": "contact sheet tile"},
            ]
            overrides = _make_overrides(tmp_path, token, overrides=items)
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)

    def test_found_true_empty_value_gives_fail(self):
        """found=true with empty value → VALIDATE_OVERRIDES_FAIL."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = _make_human_token(tmp_path)
            _make_vision_tasks(tmp_path, required_ids=["D-001"])
            items = [
                {"finding_id": "D-001", "found": True, "visual_artwork_value": "",
                 "confirmed": True, "evidence": "contact sheet tile"},
            ]
            overrides = _make_overrides(tmp_path, token, overrides=items)
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


class TestValidateOverridesFileNotFound(unittest.TestCase):

    def test_missing_overrides_file_exits2(self):
        """Overrides file doesn't exist → VALIDATE_OVERRIDES_FAIL, exit 2."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run_cli(tmp, str(Path(tmp) / "nonexistent.json"))
            self.assertEqual(proc.returncode, 2)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)

    def test_missing_vision_tasks_exits2(self):
        """vision_tasks.json doesn't exist → VALIDATE_OVERRIDES_FAIL, exit 2."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            overrides = _make_overrides(tmp_path, "TOKEN", overrides=[])
            # Don't create gpt_vision/vision_tasks.json
            proc = _run_cli(tmp, str(overrides))
            self.assertEqual(proc.returncode, 2)
            self.assertIn("VALIDATE_OVERRIDES_FAIL:", proc.stderr)

    def test_pass_token_contains_sorted_json(self):
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
                    json_str = line[len("VALIDATE_OVERRIDES_PASS:"):].strip()
                    keys = list(json.loads(json_str).keys())
                    self.assertEqual(keys, sorted(keys))
                    break


if __name__ == "__main__":
    unittest.main()
