"""Additional synthetic stress cases and version-blinded packets for a human reviewer."""

import copy
import hashlib
import json
import random

from company_summaries import refined
from company_summaries.pipeline import ROOT, load_companies, render, write_json


def create_stress_cases():
    """Generate source records and expectations separately from the production fact builder."""
    rng = random.Random(20261120)  # noqa: S311 -- reproducible test fixtures, not security
    base = load_companies()[0]
    fixtures = []
    for scenario in ("missing", "single", "interim_loss", "plaintiff", "defendant", "corporate", "appointments", "zero"):
        for variant in range(3):
            c = copy.deepcopy(base)
            cid = f"TEST-{len(fixtures) + 1:06d}"
            c["registrationNumber"] = cid
            c["profile"].update(
                companyName=f"Synthetic Stress {len(fixtures) + 1} Sdn. Bhd.",
                natureOfBusiness="Software maintenance",
                shareCapital=50000,
            )
            c["relationships"]["directors"] = [
                {"name": "Director 1", "designation": "Director", "appointedOn": "2020-01-01"},
                {"name": "Director 2", "designation": "Director", "appointedOn": "2021-01-01"},
            ]
            c["relationships"]["shareholders"] = [{"name": "Director 1", "type": "individual", "percentage": 100}]
            for y in c["financials"]["years"]:
                revenue = rng.randrange(100000, 400000)
                profit = rng.randrange(2000, 10000)
                s = y["statements"]
                s.update(
                    revenue=revenue,
                    costOfSales=revenue // 2,
                    grossProfit=revenue - revenue // 2,
                    operatingProfit=profit + 1500,
                    operatingExpenses=revenue - revenue // 2 - profit - 1500,
                    interestExpense=1500,
                    profitBeforeTax=profit,
                    taxExpense=0,
                    profitAfterTax=profit,
                    cash=50000,
                    tradeReceivables=130000,
                    inventory=20000,
                    currentAssets=200000,
                    nonCurrentAssets=300000,
                    totalAssets=500000,
                    currentLiabilities=100000,
                    totalLiabilities=300000,
                    totalEquity=200000,
                    borrowings=200000,
                    operatingCashFlow=12000,
                    capitalExpenditure=7000,
                )
                y["audit"]["opinion"] = "Unqualified"
                for group in y["ratiosAndMetrics"].values():
                    for key in group:
                        group[key] = None
            expected = {}
            if scenario == "missing":
                c["financials"]["years"] = []
                expected["missing_accounts"] = "No financial statements are supplied"
            elif scenario == "single":
                c["financials"]["years"] = c["financials"]["years"][-1:]
                expected["no_invented_trend"] = "no multi-year trend can be established"
            elif scenario == "interim_loss":
                loss = -rng.randrange(1000, 20000)
                s = c["financials"]["years"][1]["statements"]
                s.update(
                    profitAfterTax=loss,
                    profitBeforeTax=loss,
                    operatingProfit=loss + 1500,
                    operatingExpenses=s["grossProfit"] - loss - 1500,
                )
                expected["interim_loss"] = f"FY2023 profit after tax was -RM {abs(loss):,}"
            elif scenario in {"plaintiff", "defendant"}:
                role = "plaintiff" if scenario == "plaintiff" else "defendant"
                claim = rng.randrange(10000, 90000)
                c["litigation"]["cases"] = [
                    {
                        "caseNumber": f"TEST-CASE-{variant}",
                        "role": role,
                        "caseType": "Debt recovery",
                        "court": "Synthetic Court",
                        "filedOn": "2025-01-01",
                        "status": "Pending",
                        "claimAmount": claim,
                    }
                ]
                if role == "plaintiff":
                    expected["plaintiff_role"] = "1 as plaintiff and 0 as defendant"
                else:
                    expected["unproven_claim"] = f"RM {claim:,}, not proven liabilities"
            elif scenario == "corporate":
                c["relationships"]["shareholders"] = [
                    {
                        "name": "Synthetic Parent",
                        "type": "company",
                        "percentage": 100,
                        "registrationNumber": "TEST-PARENT",
                        "incorporatedIn": "Singapore",
                    }
                ]
                expected["corporate_context"] = "Synthetic Parent (100%; Singapore)"
            elif scenario == "appointments":
                c["relationships"]["directors"][0]["appointedOn"] = "2025-12-31"
                c["relationships"]["directors"][1]["appointedOn"] = "2026-01-01"
                expected["date_boundary"] = "1 of 2 listed directors was appointed during 2025"
            elif scenario == "zero":
                for y in c["financials"]["years"]:
                    y["statements"].update(
                        revenue=0,
                        costOfSales=0,
                        grossProfit=0,
                        operatingProfit=-1500,
                        operatingExpenses=1500,
                        interestExpense=0,
                        profitBeforeTax=-1500,
                        profitAfterTax=-1500,
                    )
                expected["zero_revenue"] = "Revenue was unchanged from RM 0"
            fixtures.append({"scenario": scenario, "company": c, "expected": expected})
    write_json(
        ROOT / "evaluations/stress-cases.json",
        {
            "seed": 20261120,
            "cases": fixtures,
            "limits": "New synthetic perturbations of a supplied schema, not independently sourced or held-out real companies. "
            "These become regression cases once inspected; no external generalisation estimate is claimed.",
            "renderer_sha256": hashlib.sha256((ROOT / "company_summaries/refined.py").read_bytes()).hexdigest(),
        },
    )
    return fixtures


def stress_test():
    path = ROOT / "evaluations/stress-cases.json"
    fixtures = json.loads(path.read_text())["cases"] if path.exists() else create_stress_cases()
    results = []
    for fixture in fixtures:
        c = fixture["company"]
        # All potentially relevant optional details are requested so this test isolates
        # fact extraction and safety coverage from a model's subjective ranking.
        selected = ["recent_appointments", "ownership", "interim_profit"]
        for version, renderer in (("v3", render), ("v4", refined.render)):
            text = renderer(c, selected)[0]
            checks = {name: value in text for name, value in fixture["expected"].items()}
            checks["within_budget"] = len(text.split()) <= 150
            checks["no_false_governance_claim"] = "governance concern" not in text.lower()
            checks["no_unknown_ratio_as_zero"] = "0.00 times" not in text
            results.append(
                {
                    "id": c["registrationNumber"],
                    "scenario": fixture["scenario"],
                    "version": version,
                    "passed": all(checks.values()),
                    "checks": checks,
                    "summary": text,
                }
            )
    report = {
        "evaluated_renderer_sha256": hashlib.sha256((ROOT / "company_summaries/refined.py").read_bytes()).hexdigest(),
        "cases_per_version": len(fixtures),
        "versions": {
            version: {"passed": sum(r["passed"] for r in results if r["version"] == version), "total": len(fixtures)}
            for version in ("v3", "v4")
        },
        "results": results,
        "limits": "This compares explicitly specified stress requirements, including newly added coverage; "
        "it is not an unbiased accuracy estimate or an independent human evaluation.",
    }
    write_json(ROOT / "evaluations/stress-report.json", report)
    print(json.dumps(report["versions"], indent=2))
    if report["versions"]["v4"]["passed"] != len(fixtures):
        raise ValueError("Some v4 stress requirements failed")


def has_review_input(document):
    if any(value not in (None, "", [], {}) for key, value in document.items() if key not in {"status", "ratings"}):
        return True
    if document.get("status") not in (None, "", "pending_human_review"):
        return True
    return any(
        value not in (None, "", [], {}) for row in document.get("ratings", []) for key, value in row.items() if key != "pair_id"
    )


def review_packet():
    ratings_path = ROOT / "evaluations/review-ratings.json"
    if ratings_path.exists() and has_review_input(json.loads(ratings_path.read_text())):
        # Keep the packet and its key fixed once anyone starts reviewing it.
        return
    ids = ["SYN-000029", "SYN-000217", "SYN-000286", "SYN-000302", "SYN-000451", "SYN-000545", "SYN-001203", "SYN-001829"]
    sources = {c["registrationNumber"]: c for c in load_companies() if c["registrationNumber"] in ids}
    summaries = {
        v: {
            r["registrationNumber"]: r["summary"]
            for r in [json.loads(line) for line in (ROOT / "summaries" / f"{v}.jsonl").read_text().splitlines()]
        }
        for v in ("v3", "v4", "v4-rules")
    }
    rng = random.Random(17)  # noqa: S311 -- reproducible review ordering, not security
    pairs = [(cid, versions) for cid in ids for versions in (("v3", "v4"), ("v4", "v4-rules"))]
    rng.shuffle(pairs)
    lines = [
        "# Version-blinded review packet",
        "",
        "Status: **not yet reviewed by a person**.",
        "",
        "Open `review-source-records.json` to check each company. Do not open `review-key.json` until ratings are saved.",
        "For each pair, choose A, B, tie, or neither. Judge factual accuracy first, then important omissions, "
        "clarity, and usefulness for deciding what to investigate. Record errors and time spent in `review-ratings.json`.",
        "A tie is valid. If outputs are identical, mark a tie. Do not infer a supplier approval from a summary.",
        "The packet freezes as soon as any rating, note, timing, error, omission or reviewer information is entered.",
        "",
        "There are two comparisons: writing/coverage changes and model versus rules selection. "
        "Their assignments are hidden in the separate key. This is version blinding, not a claim of double-blind research.",
        "",
    ]
    key, ratings = [], []
    for i, (cid, versions) in enumerate(pairs, 1):
        left, right = versions if rng.randrange(2) else tuple(reversed(versions))
        pair_id = f"PAIR-{i:02d}"
        lines += [f"## {pair_id} · {cid}", "", "### A", "", summaries[left][cid], "", "### B", "", summaries[right][cid], ""]
        key.append(
            {
                "pair_id": pair_id,
                "company": cid,
                "A": left,
                "B": right,
                "A_sha256": hashlib.sha256(summaries[left][cid].encode()).hexdigest(),
                "B_sha256": hashlib.sha256(summaries[right][cid].encode()).hexdigest(),
            }
        )
        ratings.append(
            {
                "pair_id": pair_id,
                "preference": None,
                "clarity_A_1_to_5": None,
                "clarity_B_1_to_5": None,
                "seconds_spent": None,
                "factual_errors": [],
                "important_omissions": [],
                "notes": "",
            }
        )
    (ROOT / "evaluations/REVIEW_PACKET.md").write_text("\n".join(lines))
    write_json(ROOT / "evaluations/review-key.json", key)
    write_json(ROOT / "evaluations/review-source-records.json", sources)
    # Never overwrite a person's completed ratings when reports are rebuilt.
    if not ratings_path.exists():
        write_json(ratings_path, {"status": "pending_human_review", "reviewer": None, "ratings": ratings})


def review_status():
    path = ROOT / "evaluations/review-ratings.json"
    if not path.exists():
        return
    ratings = json.loads(path.read_text())
    key = {row["pair_id"]: row for row in json.loads((ROOT / "evaluations/review-key.json").read_text())}
    current = {}
    for version in {assignment[side] for assignment in key.values() for side in ("A", "B")}:
        current[version] = {
            r["registrationNumber"]: r["summary"]
            for r in [json.loads(line) for line in (ROOT / "summaries" / f"{version}.jsonl").read_text().splitlines()]
        }
    matches = all(
        hashlib.sha256(current[row[side]][row["company"]].encode()).hexdigest() == row.get(f"{side}_sha256")
        for row in key.values()
        for side in ("A", "B")
    )
    completed, seen, counts = 0, set(), {}
    for row in ratings["ratings"]:
        pair_id = row["pair_id"]
        if pair_id not in key or pair_id in seen:
            raise ValueError("Unknown or duplicate review pair")
        seen.add(pair_id)
        preference = row["preference"]
        if preference is None:
            continue
        if preference not in {"A", "B", "tie", "neither"}:
            raise ValueError("Preference must be A, B, tie, or neither")
        completed += 1
        assignment = key[pair_id]
        comparison = " vs ".join(sorted([assignment["A"], assignment["B"]]))
        winner = assignment[preference] if preference in {"A", "B"} else preference
        counts.setdefault(comparison, {})
        counts[comparison][winner] = counts[comparison].get(winner, 0) + 1
    write_json(
        ROOT / "evaluations/human-review-status.json",
        {
            "status": "pending_human_review" if completed == 0 else "partial" if completed < len(key) else "completed",
            "completed_pairs": completed,
            "total_pairs": len(key),
            "matches_current_outputs": matches,
            "preferences": counts,
            "limits": "No reader usefulness or model preference result exists until people enter actual ratings. "
            "A convenience review is not a representative study.",
        },
    )


def main():
    stress_test()
    if (ROOT / "summaries/v4.jsonl").exists():
        review_packet()
        review_status()


if __name__ == "__main__":
    main()
