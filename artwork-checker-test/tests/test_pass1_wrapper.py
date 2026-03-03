"""
tests/test_pass1_wrapper.py

Unit tests for run_pass1_wrapper.py.

Uses the _ARTWORK_CHECKER_PASS1_SCRIPT env var to inject fake scripts
that simulate specific child process outcomes without running real Pass 1.
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
WRAPPER = str(REPO / "run_pass1_wrapper.py")


def _make_fake_pass1(tmp_dir: Path, exit_code: int, create_artifacts: bool) -> str:
    """
    Write a fake artwork_checker_pass1.py to tmp_dir and return its path.
    The fake script optionally creates the expected Pass 1 artifacts and exits
    with the given code.
    """
    out_repr = repr(str(tmp_dir))
    lines = ["import sys"]
    if create_artifacts:
        tasks_json = json.dumps({
            "task_hash": "abc", "required_ids": ["D-001"],
            "items": [], "page_images": {}, "contact_sheets": [],
        })
        prefill_json = json.dumps({
            "vision_audit": {"human_token": "TESTTOKEN1"}, "overrides": [],
        })
        lines += [
            "import pathlib",
            f"out = pathlib.Path({out_repr})",
            "out.mkdir(parents=True, exist_ok=True)",
            '(out / ".PASS1_DONE").write_text("done")',
            '(out / ".HUMAN_TOKEN").write_text("TESTTOKEN1")',
            "gv = out / 'gpt_vision'",
            "gv.mkdir(parents=True, exist_ok=True)",
            f"(gv / 'vision_tasks.json').write_text({repr(tasks_json)})",
            f"(gv / 'vision_overrides.prefill.json').write_text({repr(prefill_json)})",
        ]
    lines += [
        'print("fake pass1 stdout")',
        f"sys.exit({exit_code})",
    ]
    script_path = tmp_dir / "fake_pass1.py"
    script_path.write_text("\n".join(lines), encoding="utf-8")
    return str(script_path)


def _run_wrapper(fake_pass1_path: str, output_dir: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["_ARTWORK_CHECKER_PASS1_SCRIPT"] = fake_pass1_path
    return subprocess.run(
        [sys.executable, WRAPPER,
         "--copy", "dummy.xlsx",
         "--artwork", "dummy.pdf",
         "--output", output_dir],
        capture_output=True, text=True, env=env,
    )


def _parse_footer(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        if line.startswith("PASS1_WRAPPER_RESULT:"):
            return json.loads(line[len("PASS1_WRAPPER_RESULT:"):].strip())
    raise AssertionError(f"PASS1_WRAPPER_RESULT footer not found in:\n{stdout}")


class TestPass1WrapperFooterFields(unittest.TestCase):
    """Verify footer always has all required fields."""

    def _assert_footer_fields(self, footer: dict):
        for field in ("status", "returncode", "exit_code", "output_dir", "missing",
                       "human_token", "stderr_snippet"):
            self.assertIn(field, footer, f"Footer missing field: {field}")

    def test_verified_footer_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = _make_fake_pass1(tmp_path, exit_code=42, create_artifacts=True)
            proc = _run_wrapper(fake, tmp)
            footer = _parse_footer(proc.stdout)
            self._assert_footer_fields(footer)

    def test_failed_footer_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = _make_fake_pass1(tmp_path, exit_code=1, create_artifacts=False)
            proc = _run_wrapper(fake, tmp)
            footer = _parse_footer(proc.stdout)
            self._assert_footer_fields(footer)


class TestPass1WrapperScenarios(unittest.TestCase):

    def test_exit42_all_artifacts_present(self):
        """Exit 42 + all artifacts → status VERIFIED, wrapper exits 42."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = _make_fake_pass1(tmp_path, exit_code=42, create_artifacts=True)
            proc = _run_wrapper(fake, tmp)
            footer = _parse_footer(proc.stdout)
            self.assertEqual(footer["status"], "VERIFIED")
            self.assertEqual(footer["exit_code"], 42)
            self.assertEqual(proc.returncode, 42)
            self.assertEqual(footer["missing"], [])
            self.assertEqual(footer["human_token"], "TESTTOKEN1")

    def test_exit42_artifacts_missing(self):
        """Exit 42 + no artifacts → status ARTIFACT_MISSING, wrapper exits 1."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = _make_fake_pass1(tmp_path, exit_code=42, create_artifacts=False)
            proc = _run_wrapper(fake, tmp)
            footer = _parse_footer(proc.stdout)
            self.assertEqual(footer["status"], "ARTIFACT_MISSING")
            self.assertEqual(footer["exit_code"], 1)
            self.assertEqual(proc.returncode, 1)
            self.assertGreater(len(footer["missing"]), 0)

    def test_exit1_failure(self):
        """Non-zero non-42 exit → status FAILED, wrapper exits 1."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = _make_fake_pass1(tmp_path, exit_code=1, create_artifacts=False)
            proc = _run_wrapper(fake, tmp)
            footer = _parse_footer(proc.stdout)
            self.assertEqual(footer["status"], "FAILED")
            self.assertEqual(footer["exit_code"], 1)
            self.assertEqual(proc.returncode, 1)

    def test_exit0_no_pdf(self):
        """Exit 0 → status NO_PDF, wrapper exits 0."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = _make_fake_pass1(tmp_path, exit_code=0, create_artifacts=False)
            proc = _run_wrapper(fake, tmp)
            footer = _parse_footer(proc.stdout)
            self.assertEqual(footer["status"], "NO_PDF")
            self.assertEqual(footer["exit_code"], 0)
            self.assertEqual(proc.returncode, 0)

    def test_footer_is_last_line(self):
        """PASS1_WRAPPER_RESULT must be the last non-empty line on stdout."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = _make_fake_pass1(tmp_path, exit_code=42, create_artifacts=True)
            proc = _run_wrapper(fake, tmp)
            lines = [l for l in proc.stdout.splitlines() if l.strip()]
            self.assertTrue(lines[-1].startswith("PASS1_WRAPPER_RESULT:"),
                            f"Last non-empty line was: {lines[-1]!r}")

    def test_footer_json_is_sorted(self):
        """Footer JSON keys must be sorted (deterministic order)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = _make_fake_pass1(tmp_path, exit_code=42, create_artifacts=True)
            proc = _run_wrapper(fake, tmp)
            footer_line = next(
                l for l in proc.stdout.splitlines()
                if l.startswith("PASS1_WRAPPER_RESULT:")
            )
            json_str = footer_line[len("PASS1_WRAPPER_RESULT:"):].strip()
            keys = list(json.loads(json_str).keys())
            self.assertEqual(keys, sorted(keys))


if __name__ == "__main__":
    unittest.main()
