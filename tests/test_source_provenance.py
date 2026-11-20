"""Regression tests for source freshness, relevant citations, and snapshot recovery."""

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
from company_summaries import artifacts, evaluate, facts, pipeline, provenance, refined


class SourceProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.companies = pipeline.load_companies()
        self.rows = [json.loads(line) for line in Path("summaries/v4.jsonl").read_text().splitlines()]
        self.evidence = json.loads(Path("evaluations/v4-evidence.json").read_text())

    def source_file(self, root, records):
        (root / "data").mkdir(exist_ok=True)
        path = root / "data/companies.jsonl"
        path.write_text("".join(json.dumps(c) + "\n" for c in records))
        return path

    def assert_full_gate_rejects(self, root, check, records=None):
        (root / "evaluations/review-set.json").write_text(Path("evaluations/review-set.json").read_text())
        with (
            patch.object(evaluate, "ROOT", root),
            patch.object(evaluate, "load_companies", return_value=records or self.companies),
        ):
            report = evaluate.evaluate("v4")
            self.assertTrue(any(not r["checks"].get(check, True) for r in report["companies"]))
            with (
                patch("sys.argv", ["evaluate", "--version", "v4", "--require-complete"]),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as stopped,
            ):
                evaluate.main()
            self.assertEqual(stopped.exception.code, 1)

    def test_source_change_invalidates_report_and_company_response_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts.publish(root, "v4", self.rows, self.evidence)
            source = self.source_file(root, self.companies)
            (root / "evaluations/v4-report.json").write_text(Path("evaluations/v4-report.json").read_text())
            cid = self.companies[0]["registrationNumber"]
            with patch.object(viewer, "ROOT", root), patch.object(viewer, "COMPANIES", source):
                initial = viewer.get_company(cid)
                viewer.get_evaluation("v4")
                changed = copy.deepcopy(self.companies)
                changed[0]["profile"]["status"] = "Winding up"
                self.source_file(root, changed)
                current = viewer.get_company(cid)
                self.assertEqual(current.profile.status, "Winding up")
                self.assertNotEqual(initial.source_sha256, current.source_sha256)
                with self.assertRaises(HTTPException) as stale:
                    viewer.get_evaluation("v4")
                self.assertEqual(stale.exception.status_code, 409)

    def test_source_fingerprint_ignores_serialization_order_but_not_values(self):
        reordered = [{key: row[key] for key in reversed(row)} for row in reversed(self.companies)]
        self.assertEqual(artifacts.records_revision(self.companies), artifacts.records_revision(reordered))
        changed = copy.deepcopy(self.companies)
        changed[0]["profile"]["natureOfBusiness"] += " and a new activity"
        self.assertNotEqual(artifacts.records_revision(self.companies), artifacts.records_revision(changed))

    def test_irrelevant_but_existing_financial_citations_fail_full_gate(self):
        bad = copy.deepcopy(self.evidence)
        for record in bad:
            for fact in record["facts"]:
                if fact["id"] in {"performance", "cash_flow"}:
                    fact["sources"] = ["profile.companyName"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts.publish(root, "v4", self.rows, bad)
            self.assert_full_gate_rejects(root, "evidence_paths_match_facts")

    def test_citation_to_wrong_available_year_fails_full_gate(self):
        bad = copy.deepcopy(self.evidence)
        for fact in bad[0]["facts"]:
            if fact["id"] == "cash_flow":
                fact["sources"] = [path.replace("years.2.", "years.0.") for path in fact["sources"]]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts.publish(root, "v4", self.rows, bad)
            self.assert_full_gate_rejects(root, "evidence_paths_match_facts")

    def test_reevaluation_does_not_relabel_outdated_business_description_as_valid(self):
        changed = copy.deepcopy(self.companies)
        changed[0]["profile"]["natureOfBusiness"] = "Aircraft maintenance and repair"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts.publish(root, "v4", self.rows, self.evidence)
            self.assert_full_gate_rejects(root, "evidence_paths_match_facts", changed)

    def test_all_available_catalog_facts_have_independently_expected_paths(self):
        for company in self.companies:
            for builder in (facts.build_facts, refined.build_facts):
                for fact in builder(company):
                    with self.subTest(company=company["registrationNumber"], fact=fact.id):
                        self.assertEqual(set(provenance.expected_paths(company, fact.to_dict())), set(fact.sources))

    def test_partial_refresh_recovers_from_each_missing_export_without_losing_rows(self):
        for missing in (("summary",), ("evidence",), ("summary", "evidence")):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.object(pipeline, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                    pipeline.run(self.companies[:2], offline=True, version="v4")
                    paths = {
                        "summary": root / "summaries/v4-rules.jsonl",
                        "evidence": root / "evaluations/v4-rules-evidence.json",
                    }
                    for name in missing:
                        paths[name].unlink()
                    refreshed = copy.deepcopy(self.companies[:1])
                    refreshed[0]["profile"]["companyName"] = "Updated test company"
                    pipeline.run(refreshed, offline=True, version="v4", merge=True)
                    summary, proof = artifacts.read_snapshot(root, "v4-rules")
                    rows = [json.loads(line) for line in summary.splitlines()]
                    self.assertEqual(
                        {r["registrationNumber"] for r in rows}, {c["registrationNumber"] for c in self.companies[:2]}
                    )
                    self.assertIn("Updated test company", rows[0]["summary"])
                    self.assertEqual(len(json.loads(proof)), 2)
                    self.assertTrue(artifacts.mirrors_match(root, "v4-rules"))

    def test_incomplete_legacy_pair_fails_without_overwriting_remaining_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(pipeline, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                pipeline.run(self.companies[:2], offline=True, version="v4")
                (root / "evaluations/v4-rules-snapshot.json").unlink()
                (root / "evaluations/v4-rules-evidence.json").unlink()
                summary = root / "summaries/v4-rules.jsonl"
                before = summary.read_bytes()
                with self.assertRaisesRegex(RuntimeError, "Incomplete legacy"):
                    pipeline.run(self.companies[:1], offline=True, version="v4", merge=True)
                self.assertEqual(summary.read_bytes(), before)
