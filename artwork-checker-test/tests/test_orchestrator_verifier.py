"""
tests/test_orchestrator_verifier.py

Tests for orchestrator_verifier.py — verifies that the correct canonical
token is emitted for each wrapper footer status.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).parent.parent
VERIFIER = str(REPO / "orchestrator_verifier.py")


def _run_verifier(wrapper_stdout: str, wrapper_type: str | None = None) -> tuple[str, int]:
    """Write wrapper_stdout to a temp file, run orchestrator_verifier, return (token, returncode)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(wrapper_stdout)
        tmp_path = f.name
    try:
        cmd = [sys.executable, VERIFIER, "--wrapper-output", tmp_path]
        if wrapper_type:
            cmd += ["--wrapper-type", wrapper_type]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.stdout.strip(), proc.returncode
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _make_pass1_stdout(status: str, extra: dict | None = None) -> str:
    footer = {
        "exit_code": 42 if status == "VERIFIED" else (0 if status == "NO_PDF" else 1),
        "human_token": "ABCD1234" if status == "VERIFIED" else None,
        "missing": [] if status in ("VERIFIED", "NO_PDF") else ["/output/.PASS1_DONE"],
        "output_dir": "/tmp/output",
        "returncode": 42 if status == "VERIFIED" else (0 if status == "NO_PDF" else 1),
        "status": status,
        "stderr_snippet": "",
    }
    if extra:
        footer.update(extra)
    return f"some pass1 output\n{'=' * 60}\nPASS1_WRAPPER_RESULT: {json.dumps(footer, sort_keys=True)}\n"


def _make_pass2_stdout(status: str) -> str:
    footer = {
        "exit_code": 0 if status == "PASS2_COMPLETE" else 1,
        "output_dir": "/tmp/output",
        "report_path": None,
        "returncode": 0 if status == "PASS2_COMPLETE" else 1,
        "status": status,
        "stderr_snippet": "",
    }
    return f"some pass2 output\nPASS2_WRAPPER_RESULT: {json.dumps(footer, sort_keys=True)}\n"


class TestOrchestratorPass1(unittest.TestCase):

    def test_verified_gives_pass1_artifacts_verified(self):
        token, rc = _run_verifier(_make_pass1_stdout("VERIFIED"))
        self.assertEqual(token, "PASS1_ARTIFACTS_VERIFIED")
        self.assertEqual(rc, 0)

    def test_no_pdf_gives_pass1_no_pdf(self):
        token, rc = _run_verifier(_make_pass1_stdout("NO_PDF"))
        self.assertEqual(token, "PASS1_NO_PDF")
        self.assertEqual(rc, 0)

    def test_artifact_missing_gives_pass1_failed(self):
        token, rc = _run_verifier(_make_pass1_stdout("ARTIFACT_MISSING"))
        self.assertEqual(token, "PASS1_FAILED")
        self.assertEqual(rc, 1)

    def test_failed_gives_pass1_failed(self):
        token, rc = _run_verifier(_make_pass1_stdout("FAILED"))
        self.assertEqual(token, "PASS1_FAILED")
        self.assertEqual(rc, 1)

    def test_no_footer_gives_pass1_failed_exit2(self):
        token, rc = _run_verifier("no footer here\njust some stdout\n")
        self.assertEqual(token, "PASS1_FAILED")
        self.assertEqual(rc, 2)

    def test_footer_not_in_last_5_lines_not_found(self):
        # Footer buried more than 5 lines from the end
        prefix = _make_pass1_stdout("VERIFIED")
        extra_lines = "\n".join(["extra line"] * 10)
        token, rc = _run_verifier(prefix + extra_lines)
        # Footer is now beyond last 5 lines
        self.assertEqual(token, "PASS1_FAILED")
        self.assertEqual(rc, 2)

    def test_explicit_pass1_type_hint(self):
        token, rc = _run_verifier(_make_pass1_stdout("VERIFIED"), wrapper_type="pass1")
        self.assertEqual(token, "PASS1_ARTIFACTS_VERIFIED")
        self.assertEqual(rc, 0)


class TestOrchestratorPass2(unittest.TestCase):

    def test_pass2_complete(self):
        token, rc = _run_verifier(_make_pass2_stdout("PASS2_COMPLETE"), wrapper_type="pass2")
        self.assertEqual(token, "PASS2_COMPLETE")
        self.assertEqual(rc, 0)

    def test_pass2_failed(self):
        token, rc = _run_verifier(_make_pass2_stdout("PASS2_FAILED"), wrapper_type="pass2")
        self.assertEqual(token, "PASS2_FAILED")
        self.assertEqual(rc, 1)

    def test_preflight_failed(self):
        token, rc = _run_verifier(_make_pass2_stdout("PREFLIGHT_FAILED"), wrapper_type="pass2")
        self.assertEqual(token, "PASS2_FAILED")
        self.assertEqual(rc, 1)

    def test_no_footer_gives_pass2_failed_exit2(self):
        token, rc = _run_verifier("no footer\n", wrapper_type="pass2")
        self.assertEqual(token, "PASS2_FAILED")
        self.assertEqual(rc, 2)

    def test_missing_file_exits2(self):
        cmd = [sys.executable, VERIFIER, "--wrapper-output", "/nonexistent/path/out.txt"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.stdout.strip(), "PASS1_FAILED")
        self.assertEqual(proc.returncode, 2)


class TestOrchestratorAutoDetect(unittest.TestCase):
    """Without --wrapper-type, auto-detect based on prefix."""

    def test_auto_detect_pass1(self):
        token, rc = _run_verifier(_make_pass1_stdout("VERIFIED"))
        self.assertEqual(token, "PASS1_ARTIFACTS_VERIFIED")

    def test_auto_detect_pass2(self):
        token, rc = _run_verifier(_make_pass2_stdout("PASS2_COMPLETE"))
        self.assertEqual(token, "PASS2_COMPLETE")


if __name__ == "__main__":
    unittest.main()
