"""Regression and adversarial checks for mistakes that can change a screening decision."""

import copy
import json
import unittest
from unittest.mock import patch

from company_summaries.evaluate import inspect_summary, resolve
from company_summaries.facts import build_facts, follow_up
from company_summaries.pipeline import load_companies, parse_selection, render, select


class SummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.companies = {c["registrationNumber"]: c for c in load_companies()}

    def company(self, cid="SYN-000029"):
        return copy.deepcopy(self.companies[cid])

    def test_missing_accounts_are_not_zero_or_healthy(self):
        c = self.company("SYN-000302")
        text, _, _ = render(c, ["cash_debt", "quick_ratio"])
        self.assertIn("cannot be assessed", text)
        self.assertNotIn("FY2024", text)
        self.assertIn("Request recent accounts", text)

    def test_reordered_years_do_not_reverse_trend(self):
        c = self.company()
        expected = render(c, ["ownership"])[0]
        c["financials"]["years"].reverse()
        self.assertEqual(render(c, ["ownership"])[0], expected)

    def test_historical_disclaimer_survives_latest_clean_audit(self):
        text = render(self.company("SYN-000217"), [])[0]
        self.assertIn("FY2023: disclaimer of opinion", text)
        self.assertIn("FY2024: unqualified", text)

    def test_plaintiff_claim_is_not_a_defendant_liability(self):
        c = self.company("SYN-000165")
        c["litigation"]["cases"][0]["status"] = "Pending"
        text = render(c, [])[0]
        self.assertIn("1 as plaintiff and 0 as defendant", text)
        self.assertNotIn("Pending defendant claims total", text)

    def test_pending_and_judgment_are_not_proven_debt(self):
        text = render(self.company("SYN-000286"), [])[0]
        self.assertIn("RM 466,500, not proven liabilities", text)
        self.assertIn("outcome is unspecified", text)
        self.assertIn("Pending defendant winding-up petitions: 1", text)

    def test_null_ratio_is_not_rendered_as_zero(self):
        c = self.company()
        c["financials"]["years"][-1]["ratiosAndMetrics"]["liquidityAndCashFlow"]["quickRatio"] = None
        self.assertNotIn("quick_ratio", [f.id for f in build_facts(c)])
        self.assertNotIn("quick assets", render(c, ["quick_ratio"])[0])

    def test_ratio_is_a_multiple_not_a_percentage(self):
        text = render(self.company(), ["quick_ratio"])[0]
        self.assertIn("1.35 times", text)
        self.assertNotIn("135%", text)

    def test_positive_profit_does_not_hide_winding_up(self):
        c = self.company("SYN-000545")
        text = render(c, [])[0]
        self.assertIn("winding up", text)
        self.assertIn("going concern", text)
        self.assertIn("Verify winding-up status", follow_up(c)[0])

    def test_single_year_has_no_invented_trend(self):
        text = render(self.company("SYN-000802"), [])[0]
        self.assertIn("no multi-year trend can be established", text)

    def test_negative_equity_and_funding_gap_cannot_be_dropped(self):
        text = render(self.company("SYN-000451"), [])[0]
        self.assertIn("equity was negative at -RM 18,522", text)
        self.assertIn("RM 17,735", text)

    def test_shareholder_count_is_not_director_count(self):
        c = self.company()
        self.assertEqual(len(c["relationships"]["directors"]), 5)
        self.assertEqual(len(c["relationships"]["shareholders"]), 4)
        text = render(c, ["ownership"])[0]
        self.assertIn("Director 4, holds 58.25%", text)
        self.assertNotIn("five", text)

    def test_unknown_selection_cannot_inject_a_sentence(self):
        text = render(self.company(), ["This company is financially safe", "invented"])[0]
        self.assertNotIn("financially safe", text)
        self.assertNotIn("invented", text)

    def test_evaluator_detects_a_changed_figure(self):
        c = self.company()
        text = render(c, [])[0].replace("RM 5,352,856", "RM 5,352,857")
        self.assertFalse(inspect_summary(c, text)["latest_revenue"])

    def test_evaluator_checks_optional_figures_too(self):
        c = self.company()
        text = render(c, ["ownership", "quick_ratio"])[0]
        self.assertFalse(inspect_summary(c, text.replace("58.25%", "85.25%"))["optional_ownership"])
        self.assertFalse(inspect_summary(c, text.replace("1.35 times", "135 times"))["optional_quick_ratio"])

    def test_evaluator_detects_missing_audit_warning(self):
        c = self.company("SYN-000217")
        text = render(c, [])[0].replace("FY2023: disclaimer of opinion", "FY2023: unqualified")
        self.assertFalse(inspect_summary(c, text)["audit_exception_2023"])

    def test_evaluator_detects_claims_promoted_to_liabilities(self):
        c = self.company("SYN-000286")
        text = render(c, [])[0].replace("not proven liabilities", "proven liabilities")
        self.assertFalse(inspect_summary(c, text)["claims_not_liabilities"])

    def test_evidence_paths_resolve_after_year_reordering(self):
        c = self.company()
        c["financials"]["years"].reverse()
        for fact in build_facts(c):
            for path in fact.sources:
                self.assertIsNotNone(resolve(c, path))

    def test_malformed_model_selection_fails_closed(self):
        c = self.company()
        raw = {"response": {"message": {"content": json.dumps({"selected": ["fake_id"]})}}}
        with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.read_text", return_value=json.dumps(raw)):
            selected, _, _, error = select(c, build_facts(c), "test-model")
        self.assertEqual(selected, [])
        self.assertIn("Invalid fact IDs", error)

    def test_truncated_and_duplicate_selections_are_rejected(self):
        facts = build_facts(self.company())
        for response in [
            {"done_reason": "length", "message": {"content": '{"selected": []}'}},
            {"message": {"content": '{"selected": ["ownership", "ownership"]}'}},
            {"message": {"content": '{"selected": [], "summary": "Invented claim"}'}},
            {"message": {"content": '{"selected": "ownership"}'}},
        ]:
            with self.subTest(response=response), self.assertRaises(ValueError):
                parse_selection(response, facts)

    def test_cached_response_makes_no_network_request(self):
        c = self.company()
        raw = {"response": {"message": {"content": '{"selected": ["ownership"]}'}}}
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", return_value=json.dumps(raw)),
            patch("urllib.request.urlopen") as network,
        ):
            selected, _, _, error = select(c, build_facts(c), "test-model")
        network.assert_not_called()
        self.assertEqual(selected, ["ownership"])
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
