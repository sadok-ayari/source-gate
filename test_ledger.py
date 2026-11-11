"""Tests for evidence-ledger. Run with: python3 -m unittest -v"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402


def write(directory, name, text):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def codes(findings):
    return [f.code for f in findings]


class ParsingTest(unittest.TestCase):
    def test_units_split_by_paragraph_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = write(tmp, "b.md", (
                "# Title\n\n"
                "First claim with a source [S1].\n\n"
                "- list claim [S2]\n"
                "- list claim without source\n"
            ))
            units = ledger.parse_units(brief)
        self.assertEqual(len(units), 3)
        self.assertEqual(units[0].tokens, ["S1"])
        self.assertEqual(units[1].kind, "list-item")

    def test_fenced_code_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = write(tmp, "b.md", "```\nuncited code block\n```\n\nReal claim [S1].\n")
            units = ledger.parse_units(brief)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].tokens, ["S1"])

    def test_heading_is_not_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = write(tmp, "b.md", "## Results and figures\n\nA claim [S1].\n")
            units = ledger.parse_units(brief)
        self.assertEqual(len(units), 1)

    def test_table_rows_are_claims_and_rules_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = write(tmp, "b.md", "| Item | Value |\n|---|---|\n| Jobs | 1,000 [S1] |\n")
            units = ledger.parse_units(brief)
        self.assertEqual(len(units), 1)
        self.assertIn("1,000", units[0].text)

    def test_multiple_tokens_in_one_bracket(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = write(tmp, "b.md", "Claim [S1, S2].\n")
            units = ledger.parse_units(brief)
        self.assertEqual(units[0].tokens, ["S1", "S2"])


class CheckingTest(unittest.TestCase):
    SOURCES = {"S1": {"url": "https://example.org/a", "date": "2026-09-01"},
               "S2": {"url": "https://example.org/b", "date": "2026-09-01"}}

    def test_uncited_claim_blocks(self):
        unit = ledger.Unit(line=1, text="No source here.", kind="paragraph", tokens=[])
        findings = ledger.check([unit], self.SOURCES, 24)
        blocking = [f for f in findings if f.severity == ledger.BLOCKING]
        self.assertEqual(codes(blocking), ["UNCITED"])

    def test_unknown_source_blocks(self):
        unit = ledger.Unit(line=1, text="Claim [S9].", kind="paragraph", tokens=["S9"])
        findings = ledger.check([unit], self.SOURCES, 24)
        self.assertIn("UNKNOWN_SOURCE", codes(findings))

    def test_clean_claim_passes_but_reports_orphans(self):
        unit = ledger.Unit(line=1, text="Claim [S1].", kind="paragraph", tokens=["S1"])
        findings = ledger.check([unit], self.SOURCES, 24)
        self.assertEqual(codes(findings), ["ORPHAN_SOURCE"])
        self.assertEqual(findings[0].severity, ledger.WARNING)

    def test_missing_url_and_date_block(self):
        unit = ledger.Unit(line=1, text="Claim [S1].", kind="paragraph", tokens=["S1"])
        findings = ledger.check([unit], {"S1": {}}, 24)
        self.assertEqual(sorted(codes(findings)), ["NO_DATE", "NO_URL"])

    def test_stale_source_warns_only(self):
        unit = ledger.Unit(line=1, text="Claim [S1].", kind="paragraph", tokens=["S1"])
        findings = ledger.check([unit], {"S1": {"url": "u", "date": "2001-01-01"}}, 24)
        self.assertEqual(codes(findings), ["STALE"])
        self.assertEqual(findings[0].severity, ledger.WARNING)


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(HERE, "ledger.py"), *args],
                              capture_output=True, text=True)

    def test_pass_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = write(tmp, "b.md", "Claim [S1].\n")
            src = write(tmp, "s.json", json.dumps(
                {"sources": {"S1": {"url": "u", "date": "2026-09-01"}}}))
            result = self.run_cli("check", brief, "--sources", src, "--quiet")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_fail_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = write(tmp, "b.md", "Uncited claim.\n")
            result = self.run_cli("check", brief, "--quiet")
        self.assertEqual(result.returncode, 1)

    def test_json_output_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = write(tmp, "b.md", "Uncited claim.\n")
            result = self.run_cli("check", brief, "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["result"], "FAIL")
        self.assertEqual(payload["blocking"], 1)


if __name__ == "__main__":
    unittest.main()
