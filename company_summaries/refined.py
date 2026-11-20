"""v4: clearer trends, contextual detail, and short paragraphs with source trails."""

from dataclasses import replace
from datetime import date

from company_summaries.facts import Fact, follow_up, money
from company_summaries.facts import build_facts as original_facts

AS_OF = date(2025, 12, 31)


def build_facts(company):
    facts = [f for f in original_facts(company) if f.id != "capital"]
    years = sorted(enumerate(company["financials"]["years"]), key=lambda pair: pair[1]["financialYear"])
    if len(years) > 1:
        first, last = years[0][1]["statements"], years[-1][1]["statements"]
        revenue = (
            "rose" if last["revenue"] > first["revenue"] else "fell" if last["revenue"] < first["revenue"] else "was unchanged"
        )
        profit = (
            "rose"
            if last["profitAfterTax"] > first["profitAfterTax"]
            else "fell"
            if last["profitAfterTax"] < first["profitAfterTax"]
            else "was unchanged"
        )
        facts = [
            replace(
                f,
                text=f.text.replace("Revenue moved", f"Revenue {revenue}").replace(
                    "profit after tax moved", f"profit after tax {profit}"
                ),
            )
            if f.id == "performance"
            else f
            for f in facts
        ]
        for index, year in years[1:-1]:
            value = year["statements"]["profitAfterTax"]
            if value < min(first["profitAfterTax"], last["profitAfterTax"]) or value > max(
                first["profitAfterTax"], last["profitAfterTax"]
            ):
                facts.append(
                    Fact(
                        "interim_profit",
                        f"Between those endpoints, FY{year['financialYear']} profit after tax was {money(value)}.",
                        [f"financials.years.{index}.financialYear", f"financials.years.{index}.statements.profitAfterTax"],
                        value < 0 <= min(first["profitAfterTax"], last["profitAfterTax"]),
                    )
                )
    directors = company["relationships"]["directors"]
    recent = [d for d in directors if date(2025, 1, 1) <= date.fromisoformat(d["appointedOn"]) <= AS_OF]
    if recent:
        verb = "was" if len(recent) == 1 else "were"
        facts.append(
            Fact(
                "recent_appointments",
                f"{len(recent)} of {len(directors)} listed directors {verb} appointed during 2025.",
                ["relationships.directors"],
                len(recent) * 2 > len(directors),
            )
        )
    holders = company["relationships"]["shareholders"]
    for index, holder in enumerate(holders):
        if holder["type"] == "company" and holder["percentage"] > 50:
            country = holder.get("incorporatedIn") or "jurisdiction not supplied"
            facts = [f for f in facts if f.id != "ownership"]
            facts.append(
                Fact(
                    "corporate_owner",
                    f"The majority direct shareholder is {holder['name']} ({holder['percentage']:g}%; {country}).",
                    [f"relationships.shareholders.{index}.{field}" for field in ("name", "percentage")]
                    + ([f"relationships.shareholders.{index}.incorporatedIn"] if holder.get("incorporatedIn") else []),
                    True,
                )
            )
    return [
        replace(
            f,
            text=f.text.replace("1 defendant case(s) show", "1 defendant case shows").replace(
                "defendant case(s) show", "defendant cases show"
            ),
        )
        if f.id == "litigation"
        else f
        for f in facts
    ]


def rank_optional(company, facts):
    """A useful comparison: prefer context over repeating already-covered figures."""
    priorities = {
        "interim_profit": 15,
        "recent_appointments": 60,
        "ownership": 50,
        "persistent_fcf": 40,
        "cash_debt": 20,
        "quick_ratio": 10,
    }
    years = company["financials"]["years"]
    if years:
        latest = max(years, key=lambda y: y["financialYear"])
        if latest["statements"]["operatingCashFlow"] < 0:
            priorities["cash_debt"] = 80
    return [f.id for f in sorted((f for f in facts if not f.required), key=lambda f: (-priorities.get(f.id, 0), f.id))][:2]


def render(company, selected):
    facts = build_facts(company)
    question, paths = follow_up(company)
    question = "**Next check:** " + question
    used = [f for f in facts if f.required]
    for key in selected:
        fact = next((f for f in facts if f.id == key and not f.required), None)
        if fact and fact not in used and len((" ".join(f.text for f in [*used, fact]) + " " + question).split()) <= 150:
            used.append(fact)
    groups = [
        {"identity", "ownership", "corporate_owner"},
        {
            "performance",
            "missing_financials",
            "cash_flow",
            "interim_profit",
            "negative_equity",
            "working_capital",
            "cash_debt",
            "persistent_fcf",
            "quick_ratio",
        },
        {"audit", "litigation", "recent_appointments"},
    ]
    # Interim years belong immediately after endpoint comparisons, not after the cash-flow paragraph.
    order = {f.id: i for i, f in enumerate(facts)}
    if "performance" in order:
        order["interim_profit"] = order["performance"] + 0.5
    used.sort(key=lambda f: order[f.id])
    paragraphs = [" ".join(f.text for f in used if f.id in group) for group in groups]
    return "\n\n".join([p for p in paragraphs if p] + [question]), [f.to_dict() for f in used], paths
