"""Keep arithmetic, legal roles, and wording out of the model's hands."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Fact:
    id: str
    text: str
    sources: list[str]
    required: bool = False

    def to_dict(self):
        return asdict(self)


def money(value):
    return ("-" if value < 0 else "") + f"RM {abs(value):,.0f}"


def build_facts(company):
    """Return independently traceable sentences, in screening priority order."""
    facts = []

    def add(key, text, sources, required=False):
        facts.append(Fact(key, text, sources, required))

    p = company["profile"]
    add(
        "identity",
        f"{p['companyName']} is listed as {p['status'].lower()} in {p['state']}; "
        f"its recorded business is {p['natureOfBusiness'].rstrip('.')}.",
        ["profile.companyName", "profile.status", "profile.state", "profile.natureOfBusiness"],
        True,
    )
    indexed = sorted(enumerate(company["financials"]["years"]), key=lambda pair: pair[1]["financialYear"])
    if not indexed:
        add(
            "missing_financials",
            "No financial statements are supplied, so profitability and repayment capacity cannot be assessed.",
            ["financials.years"],
            True,
        )
    else:
        idx, latest = indexed[-1]
        base = f"financials.years.{idx}"
        s, fy = latest["statements"], latest["financialYear"]
        if len(indexed) > 1:
            first_idx, first = indexed[0]
            add(
                "performance",
                f"Revenue moved from {money(first['statements']['revenue'])} (FY{first['financialYear']}) "
                f"to {money(s['revenue'])} (FY{fy}); profit after tax moved from "
                f"{money(first['statements']['profitAfterTax'])} to {money(s['profitAfterTax'])} over that period.",
                [
                    f"financials.years.{first_idx}.financialYear",
                    f"financials.years.{first_idx}.statements.revenue",
                    f"financials.years.{first_idx}.statements.profitAfterTax",
                    f"{base}.financialYear",
                    f"{base}.statements.revenue",
                    f"{base}.statements.profitAfterTax",
                ],
                True,
            )
        else:
            add(
                "performance",
                f"Only FY{fy} financials are supplied: revenue was {money(s['revenue'])} "
                f"and profit after tax was {money(s['profitAfterTax'])}; no multi-year trend can be established.",
                [f"{base}.financialYear", f"{base}.statements.revenue", f"{base}.statements.profitAfterTax"],
                True,
            )
        add(
            "cash_flow",
            f"FY{fy} operating cash flow was {money(s['operatingCashFlow'])}; "
            f"free cash flow after capital expenditure was {money(s['operatingCashFlow'] - s['capitalExpenditure'])}.",
            [f"{base}.financialYear", f"{base}.statements.operatingCashFlow", f"{base}.statements.capitalExpenditure"],
            True,
        )
        audit_exceptions = [(i, y) for i, y in indexed if y["audit"]["opinion"] != "Unqualified"]
        if audit_exceptions:
            entries = [f"FY{y['financialYear']}: {y['audit']['opinion'].lower()}" for _, y in audit_exceptions]
            if latest["audit"]["opinion"] == "Unqualified":
                entries.append(f"FY{fy}: unqualified")
            add(
                "audit",
                "Audit opinions include " + "; ".join(entries) + ".",
                [f"financials.years.{i}.audit.opinion" for i, _ in indexed]
                + [f"financials.years.{i}.financialYear" for i, _ in indexed],
                True,
            )
        else:
            add("audit", f"FY{fy} audit opinion: unqualified.", [f"{base}.financialYear", f"{base}.audit.opinion"], True)
        if s["totalEquity"] < 0:
            add(
                "negative_equity",
                f"FY{fy} equity was negative at {money(s['totalEquity'])}.",
                [f"{base}.financialYear", f"{base}.statements.totalEquity"],
                True,
            )
        if s["currentAssets"] < s["currentLiabilities"]:
            add(
                "working_capital",
                f"FY{fy} current liabilities exceeded current assets by {money(s['currentLiabilities'] - s['currentAssets'])}.",
                [f"{base}.financialYear", f"{base}.statements.currentAssets", f"{base}.statements.currentLiabilities"],
                True,
            )
        add(
            "cash_debt",
            f"FY{fy} cash was {money(s['cash'])} against borrowings of {money(s['borrowings'])}.",
            [f"{base}.financialYear", f"{base}.statements.cash", f"{base}.statements.borrowings"],
        )
        if len(indexed) > 1 and all(
            y["statements"]["operatingCashFlow"] - y["statements"]["capitalExpenditure"] < 0 for _, y in indexed
        ):
            add(
                "persistent_fcf",
                "Free cash flow was negative in every supplied financial year.",
                [
                    f"financials.years.{i}.statements.{key}"
                    for i, _ in indexed
                    for key in ("operatingCashFlow", "capitalExpenditure")
                ],
            )
        quick = latest["ratiosAndMetrics"]["liquidityAndCashFlow"]["quickRatio"]
        if quick is not None:
            add(
                "quick_ratio",
                f"FY{fy} quick assets covered current liabilities {quick:.2f} times.",
                [f"{base}.financialYear", f"{base}.ratiosAndMetrics.liquidityAndCashFlow.quickRatio"],
            )

    cases = company["litigation"]["cases"]
    if not cases:
        add("litigation", "No court cases appear in the supplied record.", ["litigation.cases"], True)
    else:
        plaintiffs = sum(c["role"] == "plaintiff" for c in cases)
        defendants = len(cases) - plaintiffs
        text = f"Recorded cases: {plaintiffs} as plaintiff and {defendants} as defendant."
        pending = [c for c in cases if c["role"] == "defendant" and c["status"] == "Pending"]
        if pending:
            text += f" Pending defendant claims total {money(sum(c['claimAmount'] for c in pending))}, not proven liabilities."
        judgments = sum(c["role"] == "defendant" and c["status"] == "Judgment entered" for c in cases)
        if judgments:
            text += f" {judgments} defendant case(s) show judgment entered; the outcome is unspecified."
        petitions = sum(
            c["role"] == "defendant" and c["status"] == "Pending" and c["caseType"] == "Winding-up petition" for c in cases
        )
        if petitions:
            text += f" Pending defendant winding-up petitions: {petitions}."
        if not pending and not judgments:
            text += " None are recorded as pending defendant claims or defendant judgments."
        add("litigation", text, ["litigation.cases"], True)

    holders = company["relationships"]["shareholders"]
    if holders:
        index, largest = max(enumerate(holders), key=lambda pair: pair[1]["percentage"])
        add(
            "ownership",
            f"The largest direct shareholder, {largest['name']}, holds {largest['percentage']:g}%.",
            [f"relationships.shareholders.{index}.name", f"relationships.shareholders.{index}.percentage"],
        )
    add(
        "capital",
        f"Recorded share capital is {money(p['shareCapital'])}; this is not a current cash balance.",
        ["profile.shareCapital"],
    )
    return facts


def follow_up(company):
    """A question, never a decision or an invented explanation."""
    years = company["financials"]["years"]
    cases = company["litigation"]["cases"]
    if company["profile"]["status"] == "Winding up":
        return "Verify winding-up status and the company's ability to fulfil new commitments.", ["profile.status"]
    if company["profile"]["status"] != "Active":
        return "Clarify the recorded company status and its ability to fulfil new commitments.", ["profile.status"]
    if not years:
        return "Request recent accounts and cash-flow information before assessing financial capacity.", ["financials.years"]
    if any(y["audit"]["opinion"] != "Unqualified" for y in years):
        return "Obtain the audit reports and check whether the historical audit concerns were resolved.", ["financials.years"]
    if any(c["role"] == "defendant" and c["status"] in ("Pending", "Judgment entered") for c in cases):
        return "Clarify current case outcomes and potential effects on delivery capacity.", ["litigation.cases"]
    latest = max(years, key=lambda y: y["financialYear"])["statements"]
    if latest["totalEquity"] < 0 or latest["currentAssets"] < latest["currentLiabilities"]:
        return "Ask how near-term obligations and ongoing operations will be funded.", ["financials.years"]
    if latest["operatingCashFlow"] - latest["capitalExpenditure"] < 0:
        return "Ask how spending beyond operating cash flow is funded and whether it will continue.", ["financials.years"]
    return "Request updated accounts and confirm capacity for the proposed contract.", ["financials.years"]
