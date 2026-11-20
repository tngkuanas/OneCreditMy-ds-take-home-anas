"""Commit summary/evidence pairs with one authoritative snapshot.

JSONL and evidence JSON remain convenient exports. Readers use the single snapshot
when present, so a crash between export writes cannot expose a mixed pair.
"""

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from company_summaries.models import Company


class SourceDataError(ValueError):
    """A source file does not satisfy the supported company-record schema."""


def summary_text(rows: list[dict]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def read_snapshot(root: Path, version: str) -> tuple[str, str | None]:
    snapshot = root / "evaluations" / f"{version}-snapshot.json"
    if snapshot.exists():
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        return data["summary_jsonl"], data["evidence_json"]
    summaries = (root / "summaries" / f"{version}.jsonl").read_text(encoding="utf-8")
    evidence = root / "evaluations" / f"{version}-evidence.json"
    return summaries, evidence.read_text(encoding="utf-8") if evidence.exists() else None


def revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def artifact_revision(summary: str, evidence: str | None) -> str:
    return revision(json.dumps([summary, evidence], ensure_ascii=False))


def records_revision(records: list[dict]) -> str:
    """Fingerprint source content, independent of JSON key and company-row ordering."""
    ordered = sorted(records, key=lambda row: row["registrationNumber"])
    return revision(json.dumps(ordered, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def read_records(path: Path) -> list[dict]:
    records = []
    ids = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            company = Company.model_validate(record, strict=True)
        except (ValueError, ValidationError) as exc:
            raise SourceDataError(f"Invalid company record on line {number}: {exc}") from exc
        if company.registration_number in ids:
            raise SourceDataError(f"Duplicate company ID on line {number}: {company.registration_number}")
        ids.add(company.registration_number)
        years = [y.financial_year for y in company.financials.years]
        if len(years) > 3 or len(set(years)) != len(years):
            raise SourceDataError(f"Company {company.registration_number} must have up to three distinct financial years")
        records.append(record)
    if not records:
        raise SourceDataError("No company records found")
    return records


def mirrors_match(root: Path, version: str) -> bool:
    summaries, evidence = read_snapshot(root, version)
    summary_path = root / "summaries" / f"{version}.jsonl"
    evidence_path = root / "evaluations" / f"{version}-evidence.json"
    return (
        summary_path.exists()
        and summary_path.read_text(encoding="utf-8") == summaries
        and (evidence is None or (evidence_path.exists() and evidence_path.read_text(encoding="utf-8") == evidence))
    )


def publish(root: Path, version: str, rows: list[dict], evidence: list[dict]) -> None:
    expected = {r["registrationNumber"]: r["summary"] for r in rows}
    observed = {r["registrationNumber"]: r["summary"] for r in evidence}
    if not rows or len(expected) != len(rows) or len(observed) != len(evidence) or expected != observed:
        raise ValueError("Cannot publish empty, duplicate, or inconsistent summary/evidence records")
    summaries = summary_text(rows)
    proof = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    paths = [root / "summaries" / f"{version}.jsonl", root / "evaluations" / f"{version}-evidence.json"]
    previous = [path.read_bytes() if path.exists() else None for path in paths]
    snapshot = root / "evaluations" / f"{version}-snapshot.json"
    if not snapshot.exists() and previous[0] is not None and previous[1] is not None:
        # Migrate an existing export pair before touching either export.
        atomic_bytes(
            snapshot,
            json.dumps(
                {"summary_jsonl": previous[0].decode("utf-8"), "evidence_json": previous[1].decode("utf-8")},
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            + b"\n",
        )
    # The final replace is the commit point. Until it happens, readers see the
    # previous complete snapshot. Ordinary I/O failures also restore the exports.
    try:
        atomic_bytes(paths[0], summaries.encode("utf-8"))
        atomic_bytes(paths[1], proof.encode("utf-8"))
        atomic_bytes(
            snapshot,
            json.dumps({"summary_jsonl": summaries, "evidence_json": proof}, ensure_ascii=False, indent=2).encode("utf-8")
            + b"\n",
        )
    except OSError:
        for path, old in zip(paths, previous, strict=True):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                atomic_bytes(path, old)
        raise
