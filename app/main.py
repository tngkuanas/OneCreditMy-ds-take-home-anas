"""The viewer: shows each company's record next to the summaries your system wrote. It only reads files."""

import re
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel

from company_summaries.artifacts import (
    artifact_revision,
    mirrors_match,
    read_records,
    read_snapshot,
    records_revision,
    revision,
)

ROOT = Path(__file__).resolve().parent.parent
COMPANIES = ROOT / "data" / "companies.jsonl"
SUMMARIES = ROOT / "summaries"


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class FormerName(Model):
    name: str
    changed_on: str


class Profile(Model):
    company_name: str
    status: str
    company_type: str
    incorporation_date: str
    industry: str
    state: str
    nature_of_business: str
    share_capital: int
    former_names: list[FormerName]


class Director(Model):
    name: str
    designation: str
    appointed_on: str


class Shareholder(Model):
    type: Literal["company", "individual"]
    name: str
    percentage: float
    registration_number: str | None = None
    incorporated_in: str | None = None


class Relationships(Model):
    directors: list[Director]
    shareholders: list[Shareholder]


class Audit(Model):
    firm: str
    opinion: str


class FinancialYear(Model):
    financial_year: int
    financial_year_end: str
    audit: Audit
    statements: dict[str, int]
    ratios_and_metrics: dict[str, dict[str, float | None]]


class Financials(Model):
    years: list[FinancialYear]


class Case(Model):
    case_number: str
    role: Literal["plaintiff", "defendant"]
    case_type: str
    court: str
    filed_on: str
    status: str
    claim_amount: float


class Litigation(Model):
    cases: list[Case]


class Company(Model):
    registration_number: str
    profile: Profile
    relationships: Relationships
    financials: Financials
    litigation: Litigation
    source_sha256: str | None = None


class CompanyListItem(Model):
    registration_number: str
    company_name: str
    industry: str
    state: str


class SummaryLine(Model):
    registration_number: str
    summary: str


class SummaryVersion(Model):
    summaries: dict[str, str]
    invalid_lines: list[int]
    content_sha256: str
    artifact_sha256: str
    exports_match_snapshot: bool


class EvidenceFact(Model):
    id: str
    text: str
    sources: list[str]
    required: bool


class EvidenceRow(Model):
    registration_number: str
    summary: str
    selected: list[str]
    facts: list[EvidenceFact]
    follow_up_sources: list[str]
    response_file: str | None
    selection_error: str | None
    model: str | None
    elapsed_seconds: float | None
    word_count: int


class WordCounts(Model):
    min: int
    median: float
    max: int


class EvaluationMetrics(Model):
    version: str
    companies: int
    source_companies: int
    passed_companies: int
    checks_passed: int
    checks_total: int
    word_count: WordCounts
    challenge_cases: int
    challenge_passed: int


class EvaluationResult(Model):
    registration_number: str
    passed: bool
    checks: dict[str, bool]


class EvaluationReport(Model):
    source_sha256: str
    artifact_sha256: str
    summary_sha256: str
    metrics: EvaluationMetrics
    companies: list[EvaluationResult]
    limitations: str


app = FastAPI(title="Company summaries viewer")


def load_companies() -> list[Company]:
    lines = COMPANIES.read_text(encoding="utf-8").splitlines()
    return [Company.model_validate_json(line) for line in lines if line.strip()]


@app.get("/api/companies")
def list_companies() -> list[CompanyListItem]:
    return [
        CompanyListItem(
            registration_number=c.registration_number,
            company_name=c.profile.company_name,
            industry=c.profile.industry,
            state=c.profile.state,
        )
        for c in load_companies()
    ]


@app.get("/api/companies/{registration_number}")
def get_company(registration_number: str) -> Company:
    records = read_records(COMPANIES)
    source_hash = records_revision(records)
    for record in records:
        company = Company.model_validate(record)
        if company.registration_number == registration_number:
            company.source_sha256 = source_hash
            return company
    raise HTTPException(404, f"No company {registration_number}")


@app.get("/api/summaries")
def list_versions() -> list[str]:
    exports = {p.stem for p in SUMMARIES.glob("*.jsonl")}
    snapshots = {p.name.removesuffix("-snapshot.json") for p in (ROOT / "evaluations").glob("*-snapshot.json")}
    return sorted(exports | snapshots)


@app.get("/api/summaries/{version}")
def get_version(version: str) -> SummaryVersion:
    path = SUMMARIES / f"{version}.jsonl"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise HTTPException(404, f"No summaries/{version}.jsonl")
    if not path.is_file() and not (ROOT / "evaluations" / f"{version}-snapshot.json").is_file():
        raise HTTPException(404, f"No summaries/{version}.jsonl")
    summaries: dict[str, str] = {}
    invalid_lines: list[int] = []
    text, evidence = read_snapshot(ROOT, version)
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = SummaryLine.model_validate_json(line)
        except ValidationError:
            invalid_lines.append(number)
            continue
        summaries[row.registration_number] = row.summary
    return SummaryVersion(
        summaries=summaries,
        invalid_lines=invalid_lines,
        content_sha256=revision(text),
        artifact_sha256=artifact_revision(text, evidence),
        exports_match_snapshot=mirrors_match(ROOT, version),
    )


@app.get("/api/evidence/{version}/{registration_number}")
def get_evidence(version: str, registration_number: str) -> EvidenceRow:
    if version not in {"v3", "rules-only", "v4", "v4-rules"}:
        raise HTTPException(404, "This experiment has no sentence-level evidence")
    path = ROOT / "evaluations" / f"{version}-evidence.json"
    if not path.is_file() and not (ROOT / "evaluations" / f"{version}-snapshot.json").is_file():
        raise HTTPException(404, "Evidence is not available yet")
    _, evidence_text = read_snapshot(ROOT, version)
    if evidence_text is None:
        raise HTTPException(404, "Evidence is not available yet")
    rows = TypeAdapter(list[EvidenceRow]).validate_json(evidence_text)
    for row in rows:
        if row.registration_number == registration_number:
            return row
    raise HTTPException(404, "No evidence for this company")


@app.get("/api/evaluations/{version}")
def get_evaluation(version: str) -> EvaluationReport:
    if version not in {"v1", "v2", "v3", "rules-only", "v4", "v4-rules"}:
        raise HTTPException(404, "Unknown experiment")
    path = ROOT / "evaluations" / f"{version}-report.json"
    if not path.is_file():
        raise HTTPException(404, "Run evaluation first")
    try:
        report = EvaluationReport.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise HTTPException(409, "Evaluation format changed; rerun evaluation") from exc
    text, evidence = read_snapshot(ROOT, version)
    if report.artifact_sha256 != artifact_revision(text, evidence):
        raise HTTPException(409, "Summary changed; rerun evaluation before showing check results")
    if report.source_sha256 != records_revision(read_records(COMPANIES)):
        raise HTTPException(409, "Company records changed; rerun evaluation before showing check results")
    return report


app.mount("/", StaticFiles(directory=ROOT / "app" / "static", html=True), name="static")
