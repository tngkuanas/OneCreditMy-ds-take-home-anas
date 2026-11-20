"""Build a readable results report from saved experiment artifacts."""

import json
import statistics
from collections import Counter

from company_summaries.pipeline import ROOT, load_companies, write_json


def profile_data():
    companies = load_companies()
    years = [y for c in companies for y in c["financials"]["years"]]
    cases = [case for c in companies for case in c["litigation"]["cases"]]
    nulls = sum(v is None for y in years for group in y["ratiosAndMetrics"].values() for v in group.values())
    # Arithmetic checks use a one-ringgit tolerance for integer rounding in synthetic statements.
    identities = {
        "gross_profit": lambda s: s["revenue"] - s["costOfSales"] - s["grossProfit"],
        "operating_profit": lambda s: s["grossProfit"] - s["operatingExpenses"] - s["operatingProfit"],
        "assets": lambda s: s["currentAssets"] + s["nonCurrentAssets"] - s["totalAssets"],
        "balance_sheet": lambda s: s["totalAssets"] - s["totalLiabilities"] - s["totalEquity"],
    }
    mismatches = []
    for c in companies:
        for y in c["financials"]["years"]:
            for name, calculate in identities.items():
                residual = calculate(y["statements"])
                if abs(residual) > 1:
                    mismatches.append(
                        {"id": c["registrationNumber"], "year": y["financialYear"], "identity": name, "residual": residual}
                    )
    return {
        "companies": len(companies),
        "as_of": "2025-12-31",
        "financial_years_per_company": dict(sorted(Counter(len(c["financials"]["years"]) for c in companies).items())),
        "company_statuses": dict(Counter(c["profile"]["status"] for c in companies)),
        "audit_opinions": dict(Counter(y["audit"]["opinion"] for y in years)),
        "litigation_cases": len(cases),
        "case_roles": dict(Counter(c["role"] for c in cases)),
        "case_statuses": dict(Counter(c["status"] for c in cases)),
        "null_ratios": nulls,
        "statement_identity_checks": len(years) * len(identities),
        "statement_identity_mismatches": mismatches,
    }


def main():
    profile = profile_data()
    write_json(ROOT / "evaluations/data-profile.json", profile)
    reports = {
        v: json.loads((ROOT / "evaluations" / f"{v}-report.json").read_text())["metrics"]
        for v in ("v1", "v2", "rules-only", "v3", "v4-rules", "v4")
        if (ROOT / "evaluations" / f"{v}-report.json").exists()
    }
    final_version = "v4" if "v4" in reports else "v3"
    comparison_version = "v4-rules" if final_version == "v4" else "rules-only"
    final = json.loads((ROOT / "evaluations" / f"{final_version}-evidence.json").read_text())
    comparison = {
        r["registrationNumber"]: r
        for r in json.loads((ROOT / "evaluations" / f"{comparison_version}-evidence.json").read_text())
    }
    changed = [r["registrationNumber"] for r in final if r["summary"] != comparison[r["registrationNumber"]]["summary"]]
    cached = [json.loads((ROOT / r["response_file"]).read_text()) for r in final]
    times = [r["elapsed_seconds"] for r in cached]
    usage = {
        "version": final_version,
        "comparison_version": comparison_version,
        "model": sorted({r["model"] for r in final}),
        "provider": "local Ollama HTTP API",
        "requests": len(cached),
        "saved_first_run_seconds": round(sum(times), 2),
        "median_request_seconds": round(statistics.median(times), 2),
        "input_tokens": sum(r["response"].get("prompt_eval_count", 0) for r in cached),
        "output_tokens": sum(r["response"].get("eval_count", 0) for r in cached),
        "selection_errors": sum(r["selection_error"] is not None for r in final),
        "different_from_rules_only": len(changed),
        "different_company_ids": changed,
        "cost_note": "No billed API calls; local compute and electricity are not measured.",
    }
    write_json(ROOT / "evaluations/experiment-summary.json", usage)
    lines = [
        "# Results",
        "",
        "Generated from saved artifacts by `just evaluate`; no model calls are made by evaluation.",
        "",
        "## Dataset",
        "",
        f"- {profile['companies']} synthetic companies, as of {profile['as_of']}.",
        f"- Financial years per company: {profile['financial_years_per_company']}.",
        f"- Company statuses: {profile['company_statuses']}.",
        f"- {profile['litigation_cases']} court cases; {profile['case_roles']}.",
        f"- {profile['null_ratios']} unavailable ratio values; nulls are never treated as zero.",
        f"- {profile['statement_identity_checks']} statement arithmetic checks; "
        f"{len(profile['statement_identity_mismatches'])} discrepancies above RM 1.",
        "",
        "## Experiments",
        "",
        "| Version | Companies | Words (min / median / max) | Automated acceptance |",
        "|---|---:|---:|---|",
    ]
    for version, m in reports.items():
        w = m["word_count"]
        lines.append(
            f"| {version} | {m['companies']} | {w['min']} / {w['median']:g} / {w['max']} | "
            f"{m['passed_companies']}/{m['companies']} |"
        )
    m = reports[final_version]
    lines += [
        "",
        "v1 and v2 each cover only SYN-000029. Their automated checks are limited to identity, length, and "
        "known unsupported audit claims; exact wording checks would unfairly penalize free-form prose. "
        "See `first-review.json` for the actual source-comparison findings. No population-level baseline accuracy is claimed.",
        "",
        "## Final acceptance checks",
        "",
        f"- Coverage: {m['companies']}/{m['source_companies']}; duplicate IDs: {m['duplicate_ids']}.",
        f"- Applicable checks passed: {m['checks_passed']}/{m['checks_total']}.",
        f"- Source-read challenge cases passed: {m['challenge_passed']}/{m['challenge_cases']}.",
        f"- Summaries within the original 100-150 word target: {m['within_100_150_words']}/{m['companies']}.",
        "- Shorter summaries are allowed when extra detail adds little, especially for sparse records; there is no padding.",
        "- Safety facts take precedence over the word budget; an over-budget output would fail acceptance "
        "rather than silently lose a warning.",
        "",
        "These checks cover specified facts, legal caveats, length, and evidence paths. "
        "They are not a measured hallucination rate "
        "or proof of reader usefulness. The challenge set is purposive, AI-assisted, and not held out.",
        "",
        "## Does the LLM earn its place?",
        "",
        f"The final output differs from the rules-only comparison for **{len(changed)}/{len(final)} companies**. "
        "Required facts and follow-up rules are identical by design. "
        "Neither method is shown to improve a reviewer's decisions. "
        "The rules-only baseline is a credible simpler alternative, not a deliberately weak benchmark.",
        "",
        "## Local inference",
        "",
        f"- Model: `{', '.join(usage['model'])}` via Ollama, temperature 0, seed 42, thinking disabled.",
        f"- {usage['requests']} saved requests; {usage['selection_errors']} rejected selections.",
        f"- Sum of saved first-run request times: {usage['saved_first_run_seconds']:.2f} seconds; "
        f"median request: {usage['median_request_seconds']:.2f} seconds.",
        f"- Reported tokens: {usage['input_tokens']:,} input; {usage['output_tokens']:,} output.",
        "- These are observed local timings, not hosted API benchmarks or total project work time.",
        "- There were no billed API calls; electricity and hardware costs are unmeasured.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "just check",
        "# Optional: regenerate using the installed local model",
        "just generate",
        "just evaluate",
        "```",
        "",
    ]
    if final_version == "v4":
        stress = json.loads((ROOT / "evaluations/stress-report.json").read_text())
        human = json.loads((ROOT / "evaluations/human-review-status.json").read_text())
        trial = json.loads((ROOT / "evaluations/v4-selection-trial.json").read_text())
        layout = {}
        for v in ("v3", "v4"):
            rows = [json.loads(line) for line in (ROOT / "summaries" / f"{v}.jsonl").read_text().splitlines()]
            paragraphs = [p for row in rows for p in row["summary"].split("\n\n")]
            layout[v] = {
                "median_paragraphs_per_summary": statistics.median(len(row["summary"].split("\n\n")) for row in rows),
                "median_words_per_paragraph": statistics.median(len(p.split()) for p in paragraphs),
            }
        write_json(ROOT / "evaluations/layout-comparison.json", layout)
        lines += [
            "## Refinement and additional checks",
            "",
            "- Required-field checks bind amounts to years and fields; including both numbers somewhere is insufficient.",
            "- Majority corporate owners are included; director appointments use the record date, "
            "without inferring governance problems.",
            "- Interim losses between profitable endpoints cannot be hidden by first-versus-last comparisons.",
            f"- Synthetic stress requirements: v3 {stress['versions']['v3']['passed']}/24; "
            f"v4 {stress['versions']['v4']['passed']}/24.",
            "- These are synthetic regression requirements, including newly added coverage; "
            "they are not independent real-company accuracy measurements.",
            "- Stress tests request relevant optional facts explicitly, isolating fact extraction and rendering "
            "from model prioritisation. Human comparison is still pending.",
            f"- Median paragraphs per summary: v3 {layout['v3']['median_paragraphs_per_summary']:g}; "
            f"v4 {layout['v4']['median_paragraphs_per_summary']:g}.",
            "- Paragraph count describes layout only; reader comprehension has not been measured.",
            f"- The initial v4 trial rejected {trial['rejected_selections']}/{trial['requests']} selections. "
            "The final run constrains the model's JSON schema to the available optional IDs. The trial responses remain saved.",
            f"- Human comparison packet: {human['completed_pairs']}/{human['total_pairs']} pairs rated; "
            f"status: {human['status']}.",
            "- No human preference or review-time improvement is claimed. "
            "Use REVIEW_PACKET.md and review-ratings.json to collect actual observations.",
            "",
        ]
    (ROOT / "evaluations/RESULTS.md").write_text("\n".join(lines))
    print(json.dumps(usage, indent=2))


if __name__ == "__main__":
    main()
