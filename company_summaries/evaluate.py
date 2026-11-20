"""Offline checks against the source data; no LLM judge or paid calls."""

import argparse
import json
import statistics
from collections import Counter

from company_summaries.pipeline import ROOT, load_companies, write_json


def amount(value):
    # Separate from the renderer: the evaluator checks source values, not rendered fact objects.
    return ("-RM " if value < 0 else "RM ") + format(abs(value), ",.0f")


def inspect_summary(company, summary):
    """Check important source facts independently of the selection and rendering code."""
    checks = {}
    years = sorted(company["financials"]["years"], key=lambda y: y["financialYear"])
    checks["company_identity"] = company["profile"]["companyName"] in summary
    checks["company_status"] = company["profile"]["status"].lower() in summary.lower()
    checks["word_limit"] = 0 < len(summary.split()) <= 150
    if not years:
        checks["missing_financials"] = "No financial statements are supplied" in summary and "cannot be assessed" in summary
    else:
        latest = years[-1]
        s = latest["statements"]
        for key in ("revenue", "profitAfterTax", "operatingCashFlow"):
            checks[f"latest_{key}"] = amount(s[key]) in summary
        checks["latest_year"] = f"FY{latest['financialYear']}" in summary
        checks["free_cash_flow"] = amount(s["operatingCashFlow"] - s["capitalExpenditure"]) in summary
        if len(years) == 1:
            checks["no_invented_trend"] = "no multi-year trend can be established" in summary
        else:
            checks["earliest_revenue"] = amount(years[0]["statements"]["revenue"]) in summary
            checks["earliest_profit"] = amount(years[0]["statements"]["profitAfterTax"]) in summary
        for y in years:
            if y["audit"]["opinion"] != "Unqualified":
                checks[f"audit_exception_{y['financialYear']}"] = (
                    f"FY{y['financialYear']}: {y['audit']['opinion'].lower()}" in summary
                )
        if s["totalEquity"] < 0:
            checks["negative_equity"] = "equity was negative" in summary and amount(s["totalEquity"]) in summary
        if s["currentAssets"] < s["currentLiabilities"]:
            checks["short_term_gap"] = amount(s["currentLiabilities"] - s["currentAssets"]) in summary
        if "cash was " in summary:
            checks["optional_cash_and_debt"] = (
                f"cash was {amount(s['cash'])} against borrowings of {amount(s['borrowings'])}" in summary
            )
        if "quick assets covered" in summary:
            quick = latest["ratiosAndMetrics"]["liquidityAndCashFlow"]["quickRatio"]
            checks["optional_quick_ratio"] = quick is not None and f"{quick:.2f} times" in summary
        if "Free cash flow was negative in every supplied financial year" in summary:
            checks["optional_persistent_cash_deficit"] = len(years) > 1 and all(
                y["statements"]["operatingCashFlow"] < y["statements"]["capitalExpenditure"] for y in years
            )
    if "The largest direct shareholder" in summary:
        largest = max(company["relationships"]["shareholders"], key=lambda h: h["percentage"])
        checks["optional_ownership"] = f"{largest['name']}, holds {largest['percentage']:g}%" in summary
    if "Recorded share capital is" in summary:
        checks["optional_capital"] = f"Recorded share capital is {amount(company['profile']['shareCapital'])}" in summary
    cases = company["litigation"]["cases"]
    if not cases:
        checks["qualified_absence_of_cases"] = "No court cases appear in the supplied record" in summary
    else:
        plaintiffs = len([c for c in cases if c["role"] == "plaintiff"])
        checks["legal_roles"] = f"{plaintiffs} as plaintiff and {len(cases) - plaintiffs} as defendant" in summary
        pending = [c for c in cases if c["role"] == "defendant" and c["status"] == "Pending"]
        if pending:
            checks["pending_claim_amount"] = amount(sum(c["claimAmount"] for c in pending)) in summary
            checks["claims_not_liabilities"] = "not proven liabilities" in summary
        if any(c["role"] == "defendant" and c["status"] == "Judgment entered" for c in cases):
            checks["judgment_uncertainty"] = "outcome is unspecified" in summary
        if any(c["role"] == "defendant" and c["status"] == "Pending" and c["caseType"] == "Winding-up petition" for c in cases):
            checks["pending_petition"] = "Pending defendant winding-up petitions:" in summary
    forbidden = (
        "financially safe",
        "financially healthy",
        "approve this supplier",
        "audit independence concern",
        "warrants attention regarding independence",
        "warrants verification of independence",
    )
    checks["no_known_unsupported_claims"] = not any(phrase in summary.lower() for phrase in forbidden)
    return checks


def resolve(record, path):
    for part in path.split("."):
        record = record[int(part)] if isinstance(record, list) else record[part]
    return record


def evaluate(version):
    companies = {c["registrationNumber"]: c for c in load_companies()}
    lines = (ROOT / "summaries" / f"{version}.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    evidence_file = ROOT / "evaluations" / f"{version}-evidence.json"
    evidence = {r["registrationNumber"]: r for r in json.loads(evidence_file.read_text())} if evidence_file.exists() else {}
    ids = [r["registrationNumber"] for r in rows]
    results = []
    for row in rows:
        cid, text = row["registrationNumber"], row["summary"]
        if cid not in companies:
            results.append({"registrationNumber": cid, "passed": False, "checks": {"known_id": False}})
            continue
        checks = inspect_summary(companies[cid], text)
        if version in {"v1", "v2"}:
            # Exact amounts and sentence patterns are contracts of the final renderer,
            # not fair grading rules for freely phrased baseline summaries.
            common_checks = {"company_identity", "word_limit", "no_known_unsupported_claims"}
            checks = {key: value for key, value in checks.items() if key in common_checks}
        if version in ("v3", "rules-only"):
            e = evidence.get(cid, {})
            checks["evidence_present"] = bool(e) and e.get("summary") == text
            checks["selection_valid"] = bool(e) and e.get("selection_error") is None
            facts = e.get("facts", [])
            checks["evidence_sentences_present"] = bool(facts) and all(f["text"] in text for f in facts)
            try:
                paths = [p for f in facts for p in f["sources"]] + e.get("follow_up_sources", [])
                for path in paths:
                    resolve(companies[cid], path)
                checks["source_paths_resolve"] = bool(paths)
            except KeyError, IndexError, TypeError, ValueError:
                checks["source_paths_resolve"] = False
        results.append(
            {"registrationNumber": cid, "word_count": len(text.split()), "passed": all(checks.values()), "checks": checks}
        )
    challenge = json.loads((ROOT / "evaluations/review-set.json").read_text())
    by_id = {r["registrationNumber"]: r["summary"] for r in rows}
    challenge_results = []
    for item in challenge["companies"]:
        if version in {"v1", "v2"}:
            continue
        if item["id"] not in by_id:
            continue
        text = by_id[item["id"]]
        checks = {f"contains:{s}": s in text for s in item["must_contain"]}
        checks.update({f"excludes:{s}": s.lower() not in text.lower() for s in item.get("must_not_contain", [])})
        challenge_results.append(
            {"registrationNumber": item["id"], "reason": item["reason"], "passed": all(checks.values()), "checks": checks}
        )
    lengths = [len(r["summary"].split()) for r in rows]
    counter = Counter(k for r in results for k, ok in r["checks"].items() if not ok)
    metrics = {
        "version": version,
        "companies": len(rows),
        "source_companies": len(companies),
        "coverage": len(set(ids) & companies.keys()) / len(companies),
        "duplicate_ids": len(ids) - len(set(ids)),
        "unknown_ids": sorted(set(ids) - companies.keys()),
        "passed_companies": sum(r["passed"] for r in results),
        "checks_passed": sum(sum(r["checks"].values()) for r in results),
        "checks_total": sum(len(r["checks"]) for r in results),
        "failures_by_check": dict(counter),
        "word_count": {"min": min(lengths), "median": statistics.median(lengths), "max": max(lengths)},
        "within_100_150_words": sum(100 <= n <= 150 for n in lengths),
        "challenge_cases": len(challenge_results),
        "challenge_passed": sum(r["passed"] for r in challenge_results),
    }
    return {
        "metrics": metrics,
        "companies": results,
        "challenge": challenge_results,
        "limitations": (
            "Rule checks verify selected source facts and known failure patterns; they do not measure reader usefulness "
            "or prove absence of every misleading interpretation. "
            "Challenge cases are purposively selected and are not held out."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v3", choices=["v1", "v2", "v3", "rules-only"])
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    report = evaluate(args.version)
    write_json(ROOT / "evaluations" / f"{args.version}-report.json", report)
    print(json.dumps(report["metrics"], indent=2))
    m = report["metrics"]
    if args.require_complete and (
        m["coverage"] != 1
        or m["duplicate_ids"]
        or m["unknown_ids"]
        or m["passed_companies"] != m["companies"]
        or m["challenge_passed"] != m["challenge_cases"]
    ):
        parser.exit(1, "Acceptance checks failed.\n")


if __name__ == "__main__":
    main()
