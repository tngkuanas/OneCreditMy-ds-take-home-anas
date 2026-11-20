"""Independent evidence-path contracts for the supported summary facts.

This does not call the renderer or its fact builder. A path must identify the
source fields used by that particular fact, not merely exist in the record.
"""

import re


def expected_paths(company, fact):
    key = fact["id"]
    paths = {
        "identity": [f"profile.{field}" for field in ("companyName", "status", "state", "natureOfBusiness")],
        "litigation": ["litigation.cases"],
        "capital": ["profile.shareCapital"],
    }
    indexed = sorted(enumerate(company["financials"]["years"]), key=lambda pair: pair[1]["financialYear"])
    if not indexed:
        paths["missing_financials"] = ["financials.years"]
    else:
        last_index, last = indexed[-1]
        base = f"financials.years.{last_index}"
        paths["performance"] = [
            f"{base}.{field}" for field in ("financialYear", "statements.revenue", "statements.profitAfterTax")
        ]
        if len(indexed) > 1:
            first_index = indexed[0][0]
            paths["performance"] += [
                f"financials.years.{first_index}.{field}"
                for field in ("financialYear", "statements.revenue", "statements.profitAfterTax")
            ]
        paths["cash_flow"] = [
            f"{base}.{field}" for field in ("financialYear", "statements.operatingCashFlow", "statements.capitalExpenditure")
        ]
        paths["cash_debt"] = [f"{base}.{field}" for field in ("financialYear", "statements.cash", "statements.borrowings")]
        if last["ratiosAndMetrics"]["liquidityAndCashFlow"]["quickRatio"] is not None:
            paths["quick_ratio"] = [f"{base}.financialYear", f"{base}.ratiosAndMetrics.liquidityAndCashFlow.quickRatio"]
        if last["statements"]["totalEquity"] < 0:
            paths["negative_equity"] = [f"{base}.financialYear", f"{base}.statements.totalEquity"]
        if last["statements"]["currentAssets"] < last["statements"]["currentLiabilities"]:
            paths["working_capital"] = [
                f"{base}.{field}" for field in ("financialYear", "statements.currentAssets", "statements.currentLiabilities")
            ]
        audit_indices = (
            [i for i, _ in indexed] if any(y["audit"]["opinion"] != "Unqualified" for _, y in indexed) else [last_index]
        )
        paths["audit"] = [
            f"financials.years.{i}.{field}" for i in audit_indices for field in ("financialYear", "audit.opinion")
        ]
        if len(indexed) > 1 and all(
            y["statements"]["operatingCashFlow"] < y["statements"]["capitalExpenditure"] for _, y in indexed
        ):
            paths["persistent_fcf"] = [
                f"financials.years.{i}.statements.{field}"
                for i, _ in indexed
                for field in ("operatingCashFlow", "capitalExpenditure")
            ]
        if len(indexed) > 2:
            first = indexed[0][1]["statements"]["profitAfterTax"]
            latest = last["statements"]["profitAfterTax"]
            previous = indexed[-2][1]["statements"]["profitAfterTax"]
            endpoint, recent = latest - first, latest - previous
            if (endpoint > 0) - (endpoint < 0) != (recent > 0) - (recent < 0):
                paths["recent_profit"] = [
                    f"financials.years.{i}.{field}"
                    for i in (indexed[-2][0], last_index)
                    for field in ("financialYear", "statements.profitAfterTax")
                ]
            middle_year = re.search(r"FY(\d{4}) profit after tax was", fact["text"])
            if middle_year:
                for i, y in indexed[1:-1]:
                    value = y["statements"]["profitAfterTax"]
                    if str(y["financialYear"]) == middle_year[1] and (value < min(first, latest) or value > max(first, latest)):
                        paths["interim_profit"] = [
                            f"financials.years.{i}.financialYear",
                            f"financials.years.{i}.statements.profitAfterTax",
                        ]
    holders = company["relationships"]["shareholders"]
    if holders:
        largest = max(range(len(holders)), key=lambda i: holders[i]["percentage"])
        paths["ownership"] = [f"relationships.shareholders.{largest}.{field}" for field in ("name", "percentage")]
        for i, h in enumerate(holders):
            if h["type"] == "company" and h["percentage"] > 50:
                paths["corporate_owner"] = [f"relationships.shareholders.{i}.{field}" for field in ("name", "percentage")]
                if h.get("incorporatedIn"):
                    paths["corporate_owner"].append(f"relationships.shareholders.{i}.incorporatedIn")
    if any("2025-01-01" <= d["appointedOn"] <= "2025-12-31" for d in company["relationships"]["directors"]):
        paths["recent_appointments"] = ["relationships.directors"]
    return paths.get(key)


def follow_up_contract(company):
    years = company["financials"]["years"]
    cases = company["litigation"]["cases"]
    if company["profile"]["status"] != "Active":
        return "Verify winding-up status and the company's ability to fulfil new commitments.", ["profile.status"]
    if not years:
        return "Request recent accounts and cash-flow information before assessing financial capacity.", ["financials.years"]
    if any(y["audit"]["opinion"] != "Unqualified" for y in years):
        return "Obtain the audit reports and check whether the historical audit concerns were resolved.", ["financials.years"]
    if any(c["role"] == "defendant" and c["status"] in {"Pending", "Judgment entered"} for c in cases):
        return "Clarify current case outcomes and potential effects on delivery capacity.", ["litigation.cases"]
    s = max(years, key=lambda y: y["financialYear"])["statements"]
    if s["totalEquity"] < 0 or s["currentAssets"] < s["currentLiabilities"]:
        return "Ask how near-term obligations and ongoing operations will be funded.", ["financials.years"]
    if s["operatingCashFlow"] < s["capitalExpenditure"]:
        return "Ask how spending beyond operating cash flow is funded and whether it will continue.", ["financials.years"]
    return "Request updated accounts and confirm capacity for the proposed contract.", ["financials.years"]


def inspect_evidence(company, summary, evidence):
    facts = evidence.get("facts", [])
    ids = [f.get("id") for f in facts]
    valid = bool(facts) and len(set(ids)) == len(ids)
    for fact in facts:
        expected = expected_paths(company, fact)
        actual = fact.get("sources", [])
        valid = valid and expected is not None and len(actual) == len(expected) and set(actual) == set(expected)
        if fact["id"] == "identity":
            p = company["profile"]
            valid = valid and all(
                str(value) in fact["text"]
                for value in (p["companyName"], p["status"].lower(), p["state"], p["natureOfBusiness"].rstrip("."))
            )
    question, sources = follow_up_contract(company)
    question_valid = evidence.get("follow_up_sources") == sources and summary.endswith(question)
    remaining = " ".join(summary.split())
    for fact in facts:
        text = " ".join(fact["text"].split())
        if text not in remaining:
            valid = False
        remaining = remaining.replace(text, "", 1)
    remaining = remaining.replace("**Next check:**", "", 1).strip()
    fully_covered = " ".join(remaining.split()) == question
    return {
        "evidence_paths_match_facts": bool(valid),
        "follow_up_supported": question_valid,
        "summary_fully_traced": fully_covered,
    }
