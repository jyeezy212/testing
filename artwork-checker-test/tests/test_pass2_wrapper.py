"""
tests/test_pass2_wrapper.py

Unit tests for run_pass2_wrapper.py.

Uses the _ARTWORK_CHECKER_PASS2_SCRIPT env var to inject fake pass2 scripts.
Preflight is tested by controlling which artifacts are present in the temp dir.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).parent.parent
WRAPPER = str(REPO / "run_pass2_wrapper.py")


def _make_fake_pass2(tmp_dir: Path, exit_code: int) -> str:
    """Write a fake artwork_checker_pass2.py that just exits with exit_code."""
    script = textwrap.dedent(f"""
        import sys
        print("fake pass2 stdout")
        sys.exit({exit_code})
    """)
    script_path = tmp_dir / "fake_pass2.py"
    script_path.write_text(script, encoding="utf-8")
    return str(script_path)


def _make_vision_overrides(tmp_dir: Path, token: str, n_items: int = 0) -> Path:
    """Create a minimal valid vision_overrides.json."""
    overrides = []
    if n_items:
        overrides = [
            {"finding_id": f"D-00{i}", "found": False, "visual_artwork_value": "",
             "confirmed": True, "evidence_path": ""}
            for i in range(1, n_items + 1)
        ]
    data = {
        "vision_audit": {"human_token": token},
        "overrides": overrides,
    }
    path = tmp_dir / "vision_overrides.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _setup_pass1_artifacts(tmp_dir: Path, token: str = "TESTTOKEN", *,
                            include_vision_done: bool = True) -> None:
    """Create the expected Pass 1 artifacts in tmp_dir."""
    (tmp_dir / ".PASS1_DONE").write_text("done")
    (tmp_dir / ".HUMAN_TOKEN").write_text(token)
    if include_vision_done:
        (tmp_dir / ".VISION_DONE").write_text("{}")
    gv = tmp_dir / "gpt_vision"
    gv.mkdir(parents=True, exist_ok=True)
    tasks = {
        "task_hash": "abc123",
        "required_ids": [],
        "items": [],
        "page_images": {},
        "contact_sheets": [],
    }
    (gv / "vision_tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
    (gv / "vision_overrides.prefill.json").write_text(
        json.dumps({"vision_audit": {"human_token": token}, "overrides": []}),
        encoding="utf-8",
    )


def _run_wrapper(
    tmp_dir: Path,
    fake_pass2_path: str | None,
    overrides_path: Path,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if fake_pass2_path:
        env["_ARTWORK_CHECKER_PASS2_SCRIPT"] = fake_pass2_path
    return subprocess.run(
        [sys.executable, WRAPPER,
         "--copy", "dummy.xlsx",
         "--artwork", "dummy.pdf",
         "--output", str(tmp_dir),
         "--vision-overrides", str(overrides_path)],
        capture_output=True, text=True, env=env,
    )


def _parse_footer(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        if line.startswith("PASS2_WRAPPER_RESULT:"):
            return json.loads(line[len("PASS2_WRAPPER_RESULT:"):].strip())
    raise AssertionError(f"PASS2_WRAPPER_RESULT footer not found in:\n{stdout}")


class TestPass2WrapperFooterFields(unittest.TestCase):
    """Footer must always be present with required fields."""

    REQUIRED_FIELDS = ("status", "returncode", "exit_code", "output_dir",
                        "stderr_snippet", "report_path")

    def test_preflight_fail_has_footer(self):
        """Missing .PASS1_DONE → PREFLIGHT_FAILED footer present."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            overrides = _make_vision_overrides(tmp_path, "TOKEN")
            # No pass1 artifacts written
            proc = _run_wrapper(tmp_path, None, overrides)
            footer = _parse_footer(proc.stdout)
            for field in self.REQUIRED_FIELDS:
                self.assertIn(field, footer, f"Footer missing field: {field}")

    def test_pass2_complete_has_footer(self):
        """Happy path → PASS2_COMPLETE footer present."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _setup_pass1_artifacts(tmp_path)
            overrides = _make_vision_overrides(tmp_path, "TESTTOKEN")
            fake = _make_fake_pass2(tmp_path, exit_code=0)
            proc = _run_wrapper(tmp_path, fake, overrides)
            footer = _parse_footer(proc.stdout)
            for field in self.REQUIRED_FIELDS:
                self.assertIn(field, footer, f"Footer missing field: {field}")


class TestPass2WrapperScenarios(unittest.TestCase):

    def test_preflight_fail_missing_pass1_done(self):
        """Missing .PASS1_DONE → PREFLIGHT_FAILED, exit 1."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            overrides = _make_vision_overrides(tmp_path, "TOKEN")
            proc = _run_wrapper(tmp_path, None, overrides)
            footer = _parse_footer(proc.stdout)
            self.assertEqual(footer["status"], "PREFLIGHT_FAILED")
            self.assertEqual(footer["exit_code"], 1)
            self.assertEqual(proc.returncode, 1)

    def test_pass2_complete(self):
        """Pass 1 artifacts + valid overrides + fake pass2 exits 0 → PASS2_COMPLETE."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _setup_pass1_artifacts(tmp_path)
            overrides = _make_vision_overrides(tmp_path, "TESTTOKEN")
            fake = _make_fake_pass2(tmp_path, exit_code=0)
            proc = _run_wrapper(tmp_path, fake, overrides)
            footer = _parse_footer(proc.stdout)
            self.assertEqual(footer["status"], "PASS2_COMPLETE")
            self.assertEqual(footer["exit_code"], 0)
            self.assertEqual(proc.returncode, 0)

    def test_pass2_failed(self):
        """Pass 1 artifacts + valid overrides + fake pass2 exits 1 → PASS2_FAILED."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _setup_pass1_artifacts(tmp_path)
            overrides = _make_vision_overrides(tmp_path, "TESTTOKEN")
            fake = _make_fake_pass2(tmp_path, exit_code=1)
            proc = _run_wrapper(tmp_path, fake, overrides)
            footer = _parse_footer(proc.stdout)
            self.assertEqual(footer["status"], "PASS2_FAILED")
            self.assertEqual(footer["exit_code"], 1)
            self.assertEqual(proc.returncode, 1)

    def test_footer_is_last_line(self):
        """PASS2_WRAPPER_RESULT must be the last non-empty line on stdout."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _setup_pass1_artifacts(tmp_path)
            overrides = _make_vision_overrides(tmp_path, "TESTTOKEN")
            fake = _make_fake_pass2(tmp_path, exit_code=0)
            proc = _run_wrapper(tmp_path, fake, overrides)
            lines = [l for l in proc.stdout.splitlines() if l.strip()]
            self.assertTrue(lines[-1].startswith("PASS2_WRAPPER_RESULT:"),
                            f"Last non-empty line was: {lines[-1]!r}")

    def test_preflight_fail_missing_vision_done(self):
        """Missing .VISION_DONE → PREFLIGHT_FAILED, exit 1."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _setup_pass1_artifacts(tmp_path, include_vision_done=False)
            overrides = _make_vision_overrides(tmp_path, "TESTTOKEN")
            fake = _make_fake_pass2(tmp_path, exit_code=0)
            proc = _run_wrapper(tmp_path, fake, overrides)
            footer = _parse_footer(proc.stdout)
            self.assertEqual(footer["status"], "PREFLIGHT_FAILED")
            self.assertEqual(proc.returncode, 1)

    def test_empty_overrides_allowed_when_no_required_ids(self):
        """items=0 case: empty overrides list + empty required_ids → preflight passes."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _setup_pass1_artifacts(tmp_path)  # required_ids=[] in vision_tasks.json
            overrides = _make_vision_overrides(tmp_path, "TESTTOKEN", n_items=0)
            fake = _make_fake_pass2(tmp_path, exit_code=0)
            proc = _run_wrapper(tmp_path, fake, overrides)
            footer = _parse_footer(proc.stdout)
            self.assertNotEqual(footer["status"], "PREFLIGHT_FAILED",
                                f"Preflight should pass for items=0; got: {footer}")

    def test_footer_json_is_sorted(self):
        """Footer JSON keys must be sorted."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            proc = _run_wrapper(tmp_path, None,
                                _make_vision_overrides(tmp_path, "TOKEN"))
            footer_line = next(
                l for l in proc.stdout.splitlines()
                if l.startswith("PASS2_WRAPPER_RESULT:")
            )
            json_str = footer_line[len("PASS2_WRAPPER_RESULT:"):].strip()
            keys = list(json.loads(json_str).keys())
            self.assertEqual(keys, sorted(keys))


class TestPass2WrapperOptionA(unittest.TestCase):
    """Option A: non-exact found=false items must supply reason_not_found in overrides."""

    def _setup_with_non_exact_item(self, tmp_dir: Path, token: str = "TESTTOKEN") -> None:
        """Like _setup_pass1_artifacts but with one non-exact item in vision_tasks."""
        (tmp_dir / ".PASS1_DONE").write_text("done")
        (tmp_dir / ".HUMAN_TOKEN").write_text(token)
        (tmp_dir / ".VISION_DONE").write_text("{}")
        gv = tmp_dir / "gpt_vision"
        gv.mkdir(parents=True, exist_ok=True)
        tasks = {
            "task_hash": "abc123",
            "required_ids": ["D-001"],
            "items": [{"id": "D-001", "script_match_type": "near"}],
            "page_images": {},
            "contact_sheets": [],
        }
        (gv / "vision_tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
        (gv / "vision_overrides.prefill.json").write_text(
            json.dumps({"vision_audit": {"human_token": token}, "overrides": []}),
            encoding="utf-8",
        )

    def _make_overrides_with_reason(
        self, tmp_dir: Path, token: str, reason: str | None
    ) -> Path:
        """Create a minimal overrides file for D-001 with found=false."""
        item = {
            "finding_id": "D-001",
            "found": False,
            "visual_artwork_value": "",
            "confirmed": True,
            "evidence": "contact sheet tile",
        }
        if reason is not None:
            item["reason_not_found"] = reason
        data = {
            "vision_audit": {
                "human_token": token,
                "source": "manual_image_read",
                "task_hash": "abc123",
            },
            "overrides": [item],
        }
        path = tmp_dir / "vision_overrides.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def test_missing_reason_gives_preflight_failed(self):
        """Non-exact found=false without reason_not_found → PREFLIGHT_FAILED."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._setup_with_non_exact_item(tmp_path)
            overrides = self._make_overrides_with_reason(tmp_path, "TESTTOKEN", reason=None)
            fake = _make_fake_pass2(tmp_path, exit_code=0)
            proc = _run_wrapper(tmp_path, fake, overrides)
            footer = _parse_footer(proc.stdout)
            self.assertEqual(footer["status"], "PREFLIGHT_FAILED")
            self.assertEqual(proc.returncode, 1)

    def test_invalid_reason_gives_preflight_failed(self):
        """Non-exact found=false with invalid reason_not_found → PREFLIGHT_FAILED."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._setup_with_non_exact_item(tmp_path)
            overrides = self._make_overrides_with_reason(
                tmp_path, "TESTTOKEN", reason="just_didnt_bother"
            )
            fake = _make_fake_pass2(tmp_path, exit_code=0)
            proc = _run_wrapper(tmp_path, fake, overrides)
            footer = _parse_footer(proc.stdout)
            self.assertEqual(footer["status"], "PREFLIGHT_FAILED")
            self.assertEqual(proc.returncode, 1)

    def test_valid_reason_passes_preflight(self):
        """Non-exact found=false with valid reason_not_found → PASS2_COMPLETE."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._setup_with_non_exact_item(tmp_path)
            overrides = self._make_overrides_with_reason(
                tmp_path, "TESTTOKEN", reason="not_present_on_artwork"
            )
            fake = _make_fake_pass2(tmp_path, exit_code=0)
            proc = _run_wrapper(tmp_path, fake, overrides)
            footer = _parse_footer(proc.stdout)
            self.assertEqual(footer["status"], "PASS2_COMPLETE",
                             f"Expected PASS2_COMPLETE, got {footer}")
            self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
