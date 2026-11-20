"""Recovery from failed cached selections and preservation of in-progress reviews."""

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from company_summaries import experiments, pipeline, refined


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.company = pipeline.load_companies()[0]
        self.facts = refined.build_facts(self.company)
        self.truncated = {"done_reason": "length", "message": {"content": '{"selected":[]}'}}
        self.valid = {"done_reason": "stop", "message": {"content": '{"selected":["cash_debt"]}'}}

    def setup_root(self, root):
        (root / "prompts").mkdir()
        (root / "prompts/v4.txt").write_text(Path("prompts/v4.txt").read_text())

    def response(self, payload):
        return io.BytesIO(json.dumps(payload).encode())

    def select(self, retry=False):
        return pipeline.select(self.company, self.facts, pipeline.MODEL, "v4", retry_invalid=retry)

    def test_explicit_retry_preserves_failure_and_reuses_recovered_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_root(root)
            with (
                patch.object(pipeline, "ROOT", root),
                patch(
                    "urllib.request.urlopen", side_effect=[self.response(self.truncated), self.response(self.valid)]
                ) as network,
            ):
                first = self.select()
                original = (root / first[1]).read_bytes()
                self.assertEqual(first[3], "Truncated selection")
                retry = self.select(retry=True)
                self.assertIsNone(retry[3])
                self.assertEqual(retry[0], ["cash_debt"])
                self.assertIn(".attempt-0002.json", retry[1])
                self.assertEqual((root / first[1]).read_bytes(), original)
                self.assertEqual(self.select()[1], retry[1])
                self.assertEqual(self.select(retry=True)[1], retry[1])
                self.assertEqual(network.call_count, 2)

    def test_default_failed_cache_replay_does_not_consume_more_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            self.setup_root(Path(directory))
            with (
                patch.object(pipeline, "ROOT", Path(directory)),
                patch("urllib.request.urlopen", return_value=self.response(self.truncated)) as network,
            ):
                first = self.select()
                self.assertEqual(self.select()[1:], first[1:])
                self.assertEqual(network.call_count, 1)

    def test_repeated_failure_is_bounded_and_every_response_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_root(root)
            with (
                patch.object(pipeline, "ROOT", root),
                patch(
                    "urllib.request.urlopen",
                    side_effect=[self.response(self.truncated), self.response(self.truncated), self.response(self.valid)],
                ) as network,
            ):
                first = self.select()
                second = self.select(retry=True)
                self.assertEqual(network.call_count, 2)
                self.assertIsNotNone(second[3])
                self.assertIn(".attempt-0002.json", second[1])
                third = self.select(retry=True)
                self.assertIsNone(third[3])
                self.assertIn(".attempt-0003.json", third[1])
                self.assertEqual(len({first[1], second[1], third[1]}), 3)
                self.assertTrue(all((root / result[1]).exists() for result in (first, second, third)))
                self.assertEqual(network.call_count, 3)

    def test_corrupt_or_wrong_type_cache_can_be_retried_without_erasure(self):
        for corrupt in ("{invalid-json", "null", '{"response":null}'):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.setup_root(root)
                with (
                    patch.object(pipeline, "ROOT", root),
                    patch(
                        "urllib.request.urlopen", side_effect=[self.response(self.truncated), self.response(self.valid)]
                    ) as network,
                ):
                    first = self.select()
                    path = root / first[1]
                    path.write_text(corrupt)
                    self.assertIsNotNone(self.select()[3])
                    self.assertIsNone(self.select(retry=True)[3])
                    self.assertEqual(path.read_text(), corrupt)
                    self.assertEqual(network.call_count, 2)

    def test_cli_passes_retry_flag_and_partial_merge(self):
        with (
            patch("sys.argv", ["generate", "--company", self.company["registrationNumber"], "--retry-invalid"]),
            patch.object(pipeline, "run") as run,
        ):
            pipeline.main()
        self.assertTrue(run.call_args.kwargs["retry_invalid"])
        self.assertTrue(run.call_args.kwargs["merge"])


class ReviewFreezeTests(unittest.TestCase):
    def test_every_kind_of_review_input_freezes_the_packet(self):
        blank = {
            "status": "pending_human_review",
            "reviewer": None,
            "ratings": [
                {
                    "pair_id": "PAIR-01",
                    "preference": None,
                    "clarity_A_1_to_5": None,
                    "clarity_B_1_to_5": None,
                    "seconds_spent": None,
                    "notes": "",
                    "factual_errors": [],
                    "important_omissions": [],
                }
            ],
        }
        self.assertFalse(experiments.has_review_input(blank))
        for field, value in {
            "preference": "tie",
            "clarity_A_1_to_5": 2,
            "clarity_B_1_to_5": 4,
            "seconds_spent": 0,
            "notes": "Needs checking",
            "factual_errors": ["Wrong amount"],
            "important_omissions": ["Audit warning"],
        }.items():
            with self.subTest(field=field):
                document = copy.deepcopy(blank)
                document["ratings"][0][field] = value
                self.assertTrue(experiments.has_review_input(document))
        blank["reviewer"] = "Test reviewer"
        self.assertTrue(experiments.has_review_input(blank))

    def setup_packet(self, root):
        (root / "summaries").mkdir()
        (root / "evaluations").mkdir()
        for version in ("v3", "v4", "v4-rules"):
            (root / "summaries" / f"{version}.jsonl").write_text((Path("summaries") / f"{version}.jsonl").read_text())

    def change_first_summary(self, root, key):
        pair = key[0]
        path = root / "summaries" / f"{pair['A']}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            if row["registrationNumber"] == pair["company"]:
                row["summary"] = "Different replacement summary"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def test_notes_and_score_without_preference_preserve_packet_key_sources_and_ratings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_packet(root)
            with patch.object(experiments, "ROOT", root):
                experiments.review_packet()
                path = root / "evaluations/review-ratings.json"
                ratings = json.loads(path.read_text())
                ratings["ratings"][0].update(notes="Refers to original A", clarity_A_1_to_5=2)
                path.write_text(json.dumps(ratings))
                preserved = {
                    name: (root / "evaluations" / name).read_bytes()
                    for name in ("REVIEW_PACKET.md", "review-key.json", "review-source-records.json", "review-ratings.json")
                }
                self.change_first_summary(root, json.loads(preserved["review-key.json"]))
                experiments.review_packet()
                for name, content in preserved.items():
                    self.assertEqual((root / "evaluations" / name).read_bytes(), content)
                experiments.review_status()
                status = json.loads((root / "evaluations/human-review-status.json").read_text())
                self.assertFalse(status["matches_current_outputs"])
                self.assertEqual(status["completed_pairs"], 0)

    def test_untouched_packet_can_be_rebuilt_for_updated_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_packet(root)
            with patch.object(experiments, "ROOT", root):
                experiments.review_packet()
                path = root / "evaluations/review-key.json"
                before = path.read_bytes()
                self.change_first_summary(root, json.loads(before))
                experiments.review_packet()
                self.assertNotEqual(path.read_bytes(), before)
