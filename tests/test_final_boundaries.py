"""Boundary cases from the final iterative review."""

import base64
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from company_summaries import experiments, pipeline, provenance, refined


class FinalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.companies = pipeline.load_companies()

    def test_rejected_generation_has_nonzero_cli_exit(self):
        with (
            patch("sys.argv", ["generate"]),
            patch.object(pipeline, "run", return_value=([], [{"selection_error": "Truncated selection"}])),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as stopped,
        ):
            pipeline.main()
        self.assertEqual(stopped.exception.code, 1)

    def test_malformed_http_response_is_saved_and_can_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "prompts").mkdir()
            (root / "prompts/v4.txt").write_text(Path("prompts/v4.txt").read_text())
            company = self.companies[0]
            broken = b'{"message": incomplete'
            healthy = json.dumps({"message": {"content": '{"selected":["cash_debt"]}'}, "done_reason": "stop"}).encode()
            with (
                patch.object(pipeline, "ROOT", root),
                patch("urllib.request.urlopen", side_effect=[io.BytesIO(broken), io.BytesIO(healthy)]) as network,
            ):
                first = pipeline.select(company, refined.build_facts(company), pipeline.MODEL, "v4")
                self.assertIsNotNone(first[3])
                record = json.loads((root / first[1]).read_text())
                self.assertEqual(base64.b64decode(record["response_body_base64"]), broken)
                self.assertIn("Invalid JSON", record["response_error"])
                recovered = pipeline.select(company, refined.build_facts(company), pipeline.MODEL, "v4", retry_invalid=True)
                self.assertIsNone(recovered[3])
                self.assertEqual(network.call_count, 2)
                self.assertEqual(base64.b64decode(json.loads((root / first[1]).read_text())["response_body_base64"]), broken)

    def test_invalid_source_records_are_rejected_before_generation(self):
        variants = []
        duplicate = copy.deepcopy(self.companies[:2])
        duplicate[1]["registrationNumber"] = duplicate[0]["registrationNumber"]
        variants.append(duplicate)
        bad_role = copy.deepcopy(next(c for c in self.companies if c["litigation"]["cases"]))
        bad_role["litigation"]["cases"][0]["role"] = "witness"
        variants.append([bad_role])
        bad_status = copy.deepcopy(next(c for c in self.companies if c["litigation"]["cases"]))
        bad_status["litigation"]["cases"][0]["status"] = "Unclassified appeal"
        variants.append([bad_status])
        bad_percentage = copy.deepcopy(self.companies[0])
        bad_percentage["relationships"]["shareholders"][0]["percentage"] = 150
        variants.append([bad_percentage])
        bad_id = copy.deepcopy(self.companies[0])
        bad_id["registrationNumber"] = "../../outside-project"
        variants.append([bad_id])
        bad_year = copy.deepcopy(self.companies[0])
        bad_year["financials"]["years"][1]["financialYear"] = bad_year["financials"]["years"][0]["financialYear"]
        variants.append([bad_year])
        bad_ratio = copy.deepcopy(self.companies[0])
        bad_ratio["financials"]["years"][0]["ratiosAndMetrics"]["liquidityAndCashFlow"]["quickRatio"] = float("nan")
        variants.append([bad_ratio])
        variants.append([])
        for records in variants:
            with self.subTest(records=records[:1]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "data").mkdir()
                (root / "data/companies.jsonl").write_text("".join(json.dumps(c) + "\n" for c in records))
                with (
                    patch.object(pipeline, "ROOT", root),
                    patch("sys.argv", ["generate", "--offline"]),
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as stopped,
                ):
                    pipeline.main()
                self.assertEqual(stopped.exception.code, 1)
                self.assertFalse((root / "summaries").exists())

    def test_other_inactive_status_does_not_invent_winding_up(self):
        company = copy.deepcopy(self.companies[0])
        company["profile"]["status"] = "Dormant"
        text, facts, sources = refined.render(company, [])
        self.assertNotIn("winding-up", text)
        self.assertIn("Clarify the recorded company status", text)
        checks = provenance.inspect_evidence(company, text, {"facts": facts, "follow_up_sources": sources})
        self.assertTrue(all(checks.values()))

    def test_invalid_review_measurements_are_rejected(self):
        for field, value in [
            ("clarity_A_1_to_5", 0),
            ("clarity_B_1_to_5", 6),
            ("clarity_A_1_to_5", True),
            ("clarity_A_1_to_5", 2.5),
            ("seconds_spent", -1),
            ("seconds_spent", float("nan")),
            ("seconds_spent", float("inf")),
            ("seconds_spent", False),
            ("factual_errors", "not a list"),
        ]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                experiments.validate_review({"ratings": [{field: value}]})
        experiments.validate_review({"ratings": [{"clarity_A_1_to_5": 5, "clarity_B_1_to_5": None, "seconds_spent": 0}]})

    def test_all_catalog_values_match_the_source_contract(self):
        cases = self.companies + [
            row["company"] for row in json.loads(Path("evaluations/stress-cases.json").read_text())["cases"]
        ]
        for company in cases:
            for version, builder in (("v3", pipeline.build_facts), ("v4", refined.build_facts)):
                for fact in builder(company):
                    with self.subTest(company=company["registrationNumber"], version=version, fact=fact.id):
                        self.assertEqual(fact.text, provenance.expected_text(company, fact.to_dict(), version))

    def test_supported_optional_fact_cannot_quote_a_different_source_value(self):
        company = next(c for c in self.companies if c["registrationNumber"] == "SYN-000545")
        text, facts, paths = refined.render(company, ["interim_profit"])
        fact = next(f for f in facts if f["id"] == "interim_profit")
        old = fact["text"]
        # The wrong amount exists elsewhere in this source record.
        fact["text"] = old.replace("RM 1,142,437", "RM 13,006,124")
        text = text.replace(old, fact["text"])
        checks = provenance.inspect_evidence(company, text, {"facts": facts, "follow_up_sources": paths})
        self.assertFalse(checks["evidence_values_match_source"])
