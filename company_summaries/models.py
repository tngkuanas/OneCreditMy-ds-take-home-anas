"""Shared source-record schema and API alias conventions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, allow_inf_nan=False)


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
    share_capital: int = Field(ge=0)
    former_names: list[FormerName]


class Director(Model):
    name: str
    designation: str
    appointed_on: str


class Shareholder(Model):
    type: Literal["company", "individual"]
    name: str
    percentage: float = Field(ge=0, le=100)
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
    status: Literal["Pending", "Settled", "Dismissed", "Withdrawn", "Judgment entered"]
    claim_amount: float = Field(ge=0)


class Litigation(Model):
    cases: list[Case]


class Company(Model):
    registration_number: str = Field(pattern=r"^SYN-[0-9]{6}$")
    profile: Profile
    relationships: Relationships
    financials: Financials
    litigation: Litigation
    source_sha256: str | None = None
