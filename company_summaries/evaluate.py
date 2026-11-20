"""Offline checks against the source data; no LLM judge or paid calls."""

import argparse
import json
import re
import statistics
from collections import Counter
from datetime import date

from company_summaries.artifacts import artifact_revision, mirrors_match, read_snapshot, records_revision, revision
from company_summaries.pipeline import ROOT, load_companies, write_json
from company_summaries.provenance import inspect_evidence


def amount(value):
    # Separate from the renderer: the evaluator checks source values, not rendered fact objects.
    return ("-RM " if value < 0 else "RM ") + format(abs(value), ",.0f")


def inspect_summary(company, summary, refined=False):
    """Check important source facts independently of the selection and rendering code."""
    checks = {}
    years = sorted(company["financials"]["years"], key=lambda y: y["financialYear"])
    checks["company_identity"] = company["profile"]["companyName"] in summary
    checks["company_status"] = f"is listed as {company['profile']['status'].lower()} in " in summary
    checks["word_limit"] = 0 < len(summary.split()) <= 150
    checks["audit_opinions_match_source"] = audit_matches(years, summary)
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
    petitions = sum(
        c["role"] == "defendant" and c["status"] == "Pending" and c["caseType"] == "Winding-up petition" for c in cases
    )
    petition_counts = re.findall(r"Pending defendant winding-up petitions: (\d+)\.", summary)
    checks["pending_petition_count"] = petition_counts == ([str(petitions)] if petitions else [])
    judgments = sum(c["role"] == "defendant" and c["status"] == "Judgment entered" for c in cases)
    judgment_counts = re.findall(r"(\d+) defendant (?:case\(s\) show|case shows|cases show) judgment entered", summary)
    checks["judgment_count"] = judgment_counts == ([str(judgments)] if judgments else [])
    pending = [c for c in cases if c["role"] == "defendant" and c["status"] == "Pending"]
    claim_totals = re.findall(r"Pending defendant claims total (-?RM \d(?:[\d,]*\d)?), not proven liabilities\.", summary)
    checks["pending_claims_bound_to_status"] = claim_totals == (
        [amount(sum(c["claimAmount"] for c in pending))] if pending else []
    )
    forbidden = (
        "financially safe",
        "financially healthy",
        "approve this supplier",
        "audit independence concern",
        "warrants attention regarding independence",
        "warrants verification of independence",
    )
    checks["no_known_unsupported_claims"] = not any(phrase in summary.lower() for phrase in forbidden)
    if refined:
        checks.update(inspect_refined(company, summary))
    return checks


def audit_matches(years, summary):
    clauses = re.findall(r"(?:Audit opinions include [^.]+|FY\d{4} audit opinion: [^.]+)\.", summary)
    if not years:
        return not clauses
    exceptions = {y["financialYear"]: y["audit"]["opinion"].lower() for y in years if y["audit"]["opinion"] != "Unqualified"}
    latest = years[-1]
    expected = dict(exceptions)
    if not exceptions or latest["audit"]["opinion"] == "Unqualified":
        expected[latest["financialYear"]] = latest["audit"]["opinion"].lower()
    if len(clauses) != 1:
        return False
    clause = clauses[0]
    if clause.startswith("Audit opinions include "):
        pairs = re.findall(r"FY(\d{4}): ([^;]+)", clause.removeprefix("Audit opinions include ").removesuffix("."))
    else:
        pairs = re.findall(r"FY(\d{4}) audit opinion: (.+)", clause.removesuffix("."))
    observed = {int(year): opinion for year, opinion in pairs}
    return len(pairs) == len(expected) and observed == expected


def inspect_refined(company, summary):
    """Bind amounts to their named fields and years, not just their presence somewhere."""
    checks = {}
    years = sorted(company["financials"]["years"], key=lambda y: y["financialYear"])
    currency = r"-?RM \d(?:[\d,]*\d)?"
    trend = r"(?:rose|fell|was unchanged)"
    if len(years) == 1:
        pattern = rf"Only FY(\d{{4}}) financials are supplied: revenue was ({currency}) and profit after tax was ({currency});"
        matches = re.findall(pattern, summary)
        y = years[0]
        checks["single_year_fields_and_year"] = matches == [
            (str(y["financialYear"]), amount(y["statements"]["revenue"]), amount(y["statements"]["profitAfterTax"]))
        ]
    if len(years) > 1:
        pattern = (
            rf"Revenue ({trend}) from ({currency}) \(FY(\d{{4}})\) to ({currency}) \(FY(\d{{4}})\); "
            rf"profit after tax ({trend}) from ({currency}) to ({currency}) over that period"
        )
        match = re.search(pattern, summary)
        first, last = years[0], years[-1]
        if len(years) > 2:
            previous = years[-2]
            endpoint_delta = last["statements"]["profitAfterTax"] - first["statements"]["profitAfterTax"]
            recent_delta = last["statements"]["profitAfterTax"] - previous["statements"]["profitAfterTax"]
            matches = re.findall(
                rf"FY(\d{{4}}) profit after tax (rose|fell|was unchanged) versus FY(\d{{4}}) \(({currency})\)\.", summary
            )
            required = ((endpoint_delta > 0) - (endpoint_delta < 0)) != ((recent_delta > 0) - (recent_delta < 0))
            checks["recent_profit_reversal"] = matches == (
                [
                    (
                        str(last["financialYear"]),
                        "rose" if recent_delta > 0 else "fell" if recent_delta < 0 else "was unchanged",
                        str(previous["financialYear"]),
                        amount(previous["statements"]["profitAfterTax"]),
                    )
                ]
                if required
                else []
            )
        if match:
            values = match.groups()
            checks["amounts_bound_to_years"] = values[1:5] == (
                amount(first["statements"]["revenue"]),
                str(first["financialYear"]),
                amount(last["statements"]["revenue"]),
                str(last["financialYear"]),
            ) and values[6:] == (amount(first["statements"]["profitAfterTax"]), amount(last["statements"]["profitAfterTax"]))

            def direction(key):
                delta = last["statements"][key] - first["statements"][key]
                return "rose" if delta > 0 else "fell" if delta < 0 else "was unchanged"

            checks["trend_directions"] = values[0] == direction("revenue") and values[5] == direction("profitAfterTax")
        else:
            checks["amounts_bound_to_years"] = checks["trend_directions"] = False
        for middle in years[1:-1]:
            if (
                middle["statements"]["profitAfterTax"]
                < 0
                <= min(first["statements"]["profitAfterTax"], last["statements"]["profitAfterTax"])
            ):
                checks["interim_loss_not_hidden"] = (
                    f"FY{middle['financialYear']} profit after tax was {amount(middle['statements']['profitAfterTax'])}"
                    in summary
                )
    if years:
        latest = years[-1]
        pattern = (
            rf"FY(\d{{4}}) operating cash flow was ({currency}); free cash flow after capital expenditure was ({currency})"
        )
        match = re.search(pattern, summary)
        s = latest["statements"]
        checks["cash_amounts_bound_to_fields"] = bool(match) and match.groups() == (
            str(latest["financialYear"]),
            amount(s["operatingCashFlow"]),
            amount(s["operatingCashFlow"] - s["capitalExpenditure"]),
        )
    for holder in company["relationships"]["shareholders"]:
        if holder["type"] == "company" and holder["percentage"] > 50:
            country = holder.get("incorporatedIn") or "jurisdiction not supplied"
            checks["majority_corporate_owner"] = f"{holder['name']} ({holder['percentage']:g}%; {country})" in summary
    directors = company["relationships"]["directors"]
    recent = sum(date(2025, 1, 1) <= date.fromisoformat(d["appointedOn"]) <= date(2025, 12, 31) for d in directors)
    if "listed directors" in summary or recent * 2 > len(directors):
        checks["appointments_as_of_record_date"] = (
            f"{recent} of {len(directors)} listed directors {'was' if recent == 1 else 'were'} appointed during 2025" in summary
        )
    allowed = {amount(v) for y in years for v in y["statements"].values()}
    allowed.add(amount(company["profile"]["shareCapital"]))
    for y in years:
        s = y["statements"]
        allowed.update(
            [amount(s["operatingCashFlow"] - s["capitalExpenditure"]), amount(s["currentLiabilities"] - s["currentAssets"])]
        )
    pending = [c for c in company["litigation"]["cases"] if c["role"] == "defendant" and c["status"] == "Pending"]
    allowed.add(amount(sum(c["claimAmount"] for c in pending)))
    checks["no_unrecognised_currency_amounts"] = all(value in allowed for value in re.findall(currency, summary))
    checks["separated_reading_sections"] = len(summary.split("\n\n")) >= 3
    return checks


def resolve(record, path):
    for part in path.split("."):
        record = record[int(part)] if isinstance(record, list) else record[part]
    return record


def evaluate(version):
    records = load_companies()
    source_hash = records_revision(records)
    companies = {c["registrationNumber"]: c for c in records}
    summary_jsonl, evidence_json = read_snapshot(ROOT, version)
    lines = summary_jsonl.splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    evidence = {r["registrationNumber"]: r for r in json.loads(evidence_json)} if evidence_json else {}
    consistent = mirrors_match(ROOT, version)
    ids = [r["registrationNumber"] for r in rows]
    results = []
    for row in rows:
        cid, text = row["registrationNumber"], row["summary"]
        if cid not in companies:
            results.append({"registrationNumber": cid, "passed": False, "checks": {"known_id": False}})
            continue
        checks = inspect_summary(companies[cid], text, refined=version in {"v4", "v4-rules"})
        if version in {"v1", "v2"}:
            # Exact amounts and sentence patterns are contracts of the final renderer,
            # not fair grading rules for freely phrased baseline summaries.
            common_checks = {"company_identity", "word_limit", "no_known_unsupported_claims"}
            checks = {key: value for key, value in checks.items() if key in common_checks}
        if version in ("v3", "rules-only", "v4", "v4-rules"):
            checks["snapshot_exports_match"] = consistent
            e = evidence.get(cid, {})
            checks["evidence_present"] = bool(e) and e.get("summary") == text
            checks["selection_valid"] = bool(e) and e.get("selection_error") is None
            facts = e.get("facts", [])
            checks.update(inspect_evidence(companies[cid], text, e, version))
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
        expected = item["must_contain"]
        if version in {"v4", "v4-rules"}:
            expected = [s.replace("defendant case(s) show", "defendant cases show") for s in expected]
        checks = {f"contains:{s}": s in text for s in expected}
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
        "source_sha256": source_hash,
        "artifact_sha256": artifact_revision(summary_jsonl, evidence_json),
        "summary_sha256": revision(summary_jsonl),
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
    parser.add_argument("--version", default="v4", choices=["v1", "v2", "v3", "rules-only", "v4", "v4-rules"])
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
