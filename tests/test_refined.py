"""Stronger checks for contextual errors and newly covered information."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from company_summaries.evaluate import inspect_summary
from company_summaries.pipeline import load_companies, run, selection_schema
from company_summaries.refined import build_facts, rank_optional, render


class RefinedTests(unittest.TestCase):
    def setUp(self):
        self.company = copy.deepcopy(load_companies()[0])

    def test_clear_trends_and_short_paragraphs(self):
        text = render(self.company, [])[0]
        self.assertIn("Revenue rose", text)
        self.assertIn("profit after tax fell", text)
        self.assertEqual(len(text.split("\n\n")), 4)

    def test_swapped_amounts_cannot_pass_presence_checks(self):
        text = render(self.company, [])[0]
        corrupt = text.replace("RM 5,130,131", "TEMP").replace("RM 5,352,856", "RM 5,130,131").replace("TEMP", "RM 5,352,856")
        self.assertFalse(inspect_summary(self.company, corrupt, refined=True)["amounts_bound_to_years"])

    def test_wrong_trend_and_wrong_status_are_detected(self):
        text = render(self.company, [])[0]
        self.assertFalse(inspect_summary(self.company, text.replace("Revenue rose", "Revenue fell"), True)["trend_directions"])
        self.assertFalse(
            inspect_summary(self.company, text.replace("listed as active", "listed as inactive"))["company_status"]
        )

    def test_wrong_year_and_swapped_cash_fields_are_detected(self):
        text = render(self.company, [])[0]
        wrong_year = text.replace("(FY2022)", "(FY2021)")
        self.assertFalse(inspect_summary(self.company, wrong_year, True)["amounts_bound_to_years"])
        swapped = text.replace("RM 113,617", "TEMP").replace("-RM 239,509", "RM 113,617").replace("TEMP", "-RM 239,509")
        self.assertFalse(inspect_summary(self.company, swapped, True)["cash_amounts_bound_to_fields"])

    def test_interim_loss_between_profitable_endpoints_is_required(self):
        self.company["financials"]["years"][1]["statements"]["profitAfterTax"] = -200000
        text = render(self.company, [])[0]
        self.assertIn("FY2023 profit after tax was -RM 200,000", text)
        self.assertTrue(inspect_summary(self.company, text, True)["interim_loss_not_hidden"])

    def test_foreign_majority_owner_is_context_not_a_risk_claim(self):
        self.company["relationships"]["shareholders"] = [
            {"name": "Example Holdings", "type": "company", "percentage": 100, "incorporatedIn": "Singapore"}
        ]
        text = render(self.company, [])[0]
        self.assertIn("Example Holdings (100%; Singapore)", text)
        self.assertNotIn("foreign risk", text)
        self.assertTrue(inspect_summary(self.company, text, True)["majority_corporate_owner"])

    def test_future_appointments_do_not_enter_2025_count(self):
        self.company["relationships"]["directors"] = [
            {"name": "A", "appointedOn": "2025-01-01"},
            {"name": "B", "appointedOn": "2026-01-01"},
        ]
        text = render(self.company, ["recent_appointments"])[0]
        self.assertIn("1 of 2 listed directors was appointed during 2025", text)

    def test_majority_of_current_directors_recently_appointed_is_preserved(self):
        for director in self.company["relationships"]["directors"]:
            director["appointedOn"] = "2025-06-01"
        text = render(self.company, [])[0]
        self.assertIn("5 of 5 listed directors were appointed during 2025", text)
        missing = text.replace("5 of 5 listed directors were appointed during 2025.", "")
        self.assertFalse(inspect_summary(self.company, missing, True)["appointments_as_of_record_date"])

    def test_fabricated_extra_amount_is_detected(self):
        text = render(self.company, [])[0] + " Unexplained debt: RM 987,654,321."
        self.assertFalse(inspect_summary(self.company, text, True)["no_unrecognised_currency_amounts"])

    def test_critical_facts_are_not_removed_to_fit_word_limit(self):
        self.company["profile"]["natureOfBusiness"] = " ".join(["business"] * 160)
        text = render(self.company, ["ownership"])[0]
        self.assertIn("FY2024 audit opinion", text)
        self.assertFalse(inspect_summary(self.company, text, True)["word_limit"])

    def test_partial_run_preserves_other_companies(self):
        companies = load_companies()[:2]
        with tempfile.TemporaryDirectory() as directory, patch("company_summaries.pipeline.ROOT", Path(directory)):
            run(companies, offline=True, version="v4")
            run(companies[:1], offline=True, version="v4", merge=True)
            path = Path(directory) / "summaries/v4-rules.jsonl"
            self.assertEqual(len(path.read_text().splitlines()), 2)

    def test_failed_run_leaves_previous_output_intact(self):
        with tempfile.TemporaryDirectory() as directory, patch("company_summaries.pipeline.ROOT", Path(directory)):
            run([self.company], offline=True, version="v4")
            path = Path(directory) / "summaries/v4-rules.jsonl"
            original = path.read_text()
            with (
                patch("company_summaries.refined.render", side_effect=ValueError("Interrupted")),
                self.assertRaises(ValueError),
            ):
                run([self.company], offline=True, version="v4")
            self.assertEqual(path.read_text(), original)

    def test_ranking_prefers_board_context_over_repeating_a_ratio(self):
        chosen = rank_optional(self.company, build_facts(self.company))
        self.assertIn("recent_appointments", chosen)
        self.assertNotIn("quick_ratio", chosen)

    def test_schema_constrains_model_to_actual_optional_ids(self):
        facts = build_facts(self.company)
        schema = selection_schema(facts)["properties"]["selected"]
        self.assertEqual(set(schema["items"]["enum"]), {f.id for f in facts if not f.required})
        self.assertNotIn("audit", schema["items"]["enum"])
        empty = selection_schema([f for f in facts if f.required])["properties"]["selected"]
        self.assertEqual(empty["maxItems"], 0)
