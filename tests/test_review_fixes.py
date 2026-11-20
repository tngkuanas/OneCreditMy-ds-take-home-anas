"""Full-gate regressions for the review's falsified summary/evidence pairs."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import main as viewer
from company_summaries import artifacts, evaluate, pipeline, refined


class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.companies = {c["registrationNumber"]: c for c in pipeline.load_companies()}
        self.rows = [json.loads(line) for line in Path("summaries/v4.jsonl").read_text().splitlines()]
        self.evidence = json.loads(Path("evaluations/v4-evidence.json").read_text())

    def assert_gate_rejects(self, cid, old, new, failed_check):
        rows, evidence = copy.deepcopy(self.rows), copy.deepcopy(self.evidence)
        for row in rows:
            if row["registrationNumber"] == cid:
                self.assertIn(old, row["summary"])
                row["summary"] = row["summary"].replace(old, new)
        for row in evidence:
            if row["registrationNumber"] == cid:
                row["summary"] = row["summary"].replace(old, new)
                for fact in row["facts"]:
                    fact["text"] = fact["text"].replace(old, new)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts.publish(root, "v4", rows, evidence)
            (root / "evaluations/review-set.json").write_text(Path("evaluations/review-set.json").read_text())
            with patch.object(evaluate, "ROOT", root):
                report = evaluate.evaluate("v4")
                with (
                    patch("sys.argv", ["evaluate", "--version", "v4", "--require-complete"]),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as stopped,
                ):
                    evaluate.main()
                self.assertEqual(stopped.exception.code, 1)
        result = next(r for r in report["companies"] if r["registrationNumber"] == cid)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"][failed_check])

    def test_single_year_revenue_profit_swap_fails_full_gate(self):
        self.assert_gate_rejects(
            "SYN-000802",
            "revenue was RM 27,799,367 and profit after tax was -RM 2,575,829",
            "revenue was -RM 2,575,829 and profit after tax was RM 27,799,367",
            "single_year_fields_and_year",
        )

    def test_wrong_single_year_fails_full_gate(self):
        self.assert_gate_rejects(
            "SYN-001158", "Only FY2024 financials", "Only FY2023 financials", "single_year_fields_and_year"
        )

    def test_invented_clean_or_adverse_opinion_fails(self):
        self.assert_gate_rejects(
            "SYN-000029", "audit opinion: unqualified.", "audit opinion: adverse.", "audit_opinions_match_source"
        )
        self.assert_gate_rejects(
            "SYN-000217", "FY2023: disclaimer of opinion", "FY2023: unqualified", "audit_opinions_match_source"
        )

    def test_wrong_petition_count_outside_challenge_set_fails(self):
        self.assert_gate_rejects(
            "SYN-001389",
            "Pending defendant winding-up petitions: 1.",
            "Pending defendant winding-up petitions: 0.",
            "pending_petition_count",
        )

    def test_wrong_judgment_count_fails(self):
        self.assert_gate_rejects(
            "SYN-000286", "1 defendant case shows judgment entered", "2 defendant cases show judgment entered", "judgment_count"
        )

    def test_latest_reversal_cannot_be_dropped(self):
        c = self.companies["SYN-000282"]
        text = refined.render(c, [])[0]
        required = "FY2024 profit after tax fell versus FY2023 (RM 2,026,448)."
        self.assertIn(required, text)
        self.assertFalse(evaluate.inspect_summary(c, text.replace(required, ""), True)["recent_profit_reversal"])

    def test_flat_endpoints_do_not_hide_recent_decline(self):
        c = copy.deepcopy(self.companies["SYN-000029"])
        for year, value in zip(c["financials"]["years"], [100, 200, 100], strict=True):
            year["statements"]["profitAfterTax"] = value
        text = refined.render(c, [])[0]
        self.assertIn("FY2024 profit after tax fell versus FY2023 (RM 200).", text)
        self.assertTrue(evaluate.inspect_summary(c, text, True)["recent_profit_reversal"])

    def test_no_audit_can_be_invented_for_missing_accounts(self):
        c = self.companies["SYN-000302"]
        text = refined.render(c, [])[0] + " FY2024 audit opinion: unqualified."
        self.assertFalse(evaluate.inspect_summary(c, text, True)["audit_opinions_match_source"])

    def test_failed_publish_rolls_back_both_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_rows, old_evidence = self.rows[:1], self.evidence[:1]
            artifacts.publish(root, "v4", old_rows, old_evidence)
            before = artifacts.read_snapshot(root, "v4")
            actual_write = artifacts.atomic_bytes
            failed = False

            def fail_second_export(path, data):
                nonlocal failed
                if path.name == "v4-evidence.json" and not failed:
                    failed = True
                    raise OSError("Simulated evidence failure")
                actual_write(path, data)

            with patch.object(artifacts, "atomic_bytes", side_effect=fail_second_export), self.assertRaises(OSError):
                artifacts.publish(root, "v4", self.rows[1:2], self.evidence[1:2])
            self.assertEqual(artifacts.read_snapshot(root, "v4"), before)
            self.assertTrue(artifacts.mirrors_match(root, "v4"))

    def test_hard_interruption_exposes_old_snapshot_and_flags_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts.publish(root, "v4", self.rows[:1], self.evidence[:1])
            before = artifacts.read_snapshot(root, "v4")
            actual_write = artifacts.atomic_bytes

            def interrupt(path, data):
                if path.name == "v4-snapshot.json":
                    raise KeyboardInterrupt
                actual_write(path, data)

            with patch.object(artifacts, "atomic_bytes", side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
                artifacts.publish(root, "v4", self.rows[1:2], self.evidence[1:2])
            self.assertEqual(artifacts.read_snapshot(root, "v4"), before)
            self.assertFalse(artifacts.mirrors_match(root, "v4"))
            with patch.object(viewer, "ROOT", root), patch.object(viewer, "SUMMARIES", root / "summaries"):
                self.assertEqual(set(viewer.get_version("v4").summaries), {self.rows[0]["registrationNumber"]})
                self.assertEqual(viewer.get_evidence("v4", self.rows[0]["registrationNumber"]).summary, self.rows[0]["summary"])
            # Re-publishing repairs exports from cached data without changing the snapshot.
            artifacts.publish(root, "v4", self.rows[:1], self.evidence[:1])
            self.assertTrue(artifacts.mirrors_match(root, "v4"))

    def test_failure_at_snapshot_commit_restores_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts.publish(root, "v4", self.rows[:1], self.evidence[:1])
            before = artifacts.read_snapshot(root, "v4")
            actual_write = artifacts.atomic_bytes

            def fail_commit(path, data):
                if path.name == "v4-snapshot.json":
                    raise OSError("Commit failed")
                actual_write(path, data)

            with patch.object(artifacts, "atomic_bytes", side_effect=fail_commit), self.assertRaises(OSError):
                artifacts.publish(root, "v4", self.rows[1:2], self.evidence[1:2])
            self.assertEqual(artifacts.read_snapshot(root, "v4"), before)
            self.assertTrue(artifacts.mirrors_match(root, "v4"))

    def test_legacy_pair_migration_survives_interruption_between_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts.publish(root, "v4", self.rows[:1], self.evidence[:1])
            (root / "evaluations/v4-snapshot.json").unlink()
            before = artifacts.read_snapshot(root, "v4")
            actual_write = artifacts.atomic_bytes

            def interrupt_second_export(path, data):
                if path.name == "v4-evidence.json":
                    raise KeyboardInterrupt
                actual_write(path, data)

            with (
                patch.object(artifacts, "atomic_bytes", side_effect=interrupt_second_export),
                self.assertRaises(KeyboardInterrupt),
            ):
                artifacts.publish(root, "v4", self.rows[1:2], self.evidence[1:2])
            self.assertEqual(artifacts.read_snapshot(root, "v4"), before)
            self.assertFalse(artifacts.mirrors_match(root, "v4"))

    def test_mismatched_records_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            artifacts.publish(Path(directory), "v4", self.rows[:1], self.evidence[1:2])

    def test_missing_exports_do_not_erase_committed_viewer_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts.publish(root, "v4", self.rows[:1], self.evidence[:1])
            (root / "summaries/v4.jsonl").unlink()
            (root / "evaluations/v4-evidence.json").unlink()
            with patch.object(viewer, "ROOT", root), patch.object(viewer, "SUMMARIES", root / "summaries"):
                self.assertIn("v4", viewer.list_versions())
                self.assertFalse(viewer.get_version("v4").exports_match_snapshot)
                self.assertEqual(viewer.get_evidence("v4", self.rows[0]["registrationNumber"]).summary, self.rows[0]["summary"])

    def test_stale_evaluation_cannot_show_green_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts.publish(root, "v4", self.rows[:1], self.evidence[:1])
            report = json.loads(Path("evaluations/v4-report.json").read_text())
            report["summary_sha256"] = "outdated"
            report["artifact_sha256"] = "outdated"
            (root / "evaluations/v4-report.json").write_text(json.dumps(report))
            with patch.object(viewer, "ROOT", root), self.assertRaises(HTTPException) as error:
                viewer.get_evaluation("v4")
            self.assertEqual(error.exception.status_code, 409)

    def test_evidence_only_change_invalidates_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts.publish(root, "v4", self.rows, self.evidence)
            report = json.loads(Path("evaluations/v4-report.json").read_text())
            report["artifact_sha256"] = artifacts.artifact_revision(*artifacts.read_snapshot(root, "v4"))
            path = root / "evaluations/v4-report.json"
            path.write_text(json.dumps(report))
            with patch.object(viewer, "ROOT", root):
                viewer.get_evaluation("v4")
                changed = copy.deepcopy(self.evidence)
                changed[0]["selection_error"] = "Simulated failed selection"
                artifacts.publish(root, "v4", self.rows, changed)
                with self.assertRaises(HTTPException) as error:
                    viewer.get_evaluation("v4")
                self.assertEqual(error.exception.status_code, 409)
                # Reports from the pre-fingerprint format also require re-evaluation.
                del report["artifact_sha256"]
                path.write_text(json.dumps(report))
                with self.assertRaises(HTTPException) as legacy:
                    viewer.get_evaluation("v4")
                self.assertEqual(legacy.exception.status_code, 409)
