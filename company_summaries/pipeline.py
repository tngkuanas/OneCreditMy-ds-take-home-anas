"""Small local LLM selector with cached responses and a deterministic renderer."""

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from company_summaries.artifacts import publish, read_snapshot
from company_summaries.facts import build_facts, follow_up

ROOT = Path(__file__).resolve().parents[1]
MODEL = "qwen3.5:9b"
ENDPOINT = "http://127.0.0.1:11434/api/chat"
SCHEMA = {
    "type": "object",
    "properties": {"selected": {"type": "array", "items": {"type": "string"}, "maxItems": 2}},
    "required": ["selected"],
    "additionalProperties": False,
}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_companies():
    return [json.loads(line) for line in (ROOT / "data/companies.jsonl").read_text().splitlines() if line.strip()]


def render(company, selected):
    facts = build_facts(company)
    required = [fact for fact in facts if fact.required]
    question, question_sources = follow_up(company)
    # Safety facts cannot be dropped by the model or to fit an arbitrary word target.
    used = list(required)
    for fact_id in selected:
        fact = next((fact for fact in facts if fact.id == fact_id and not fact.required), None)
        if fact and fact not in used:
            proposed = " ".join(f.text for f in [*used, fact]) + " " + question
            if len(proposed.split()) <= 150:
                used.append(fact)
    order = {fact.id: i for i, fact in enumerate(facts)}
    used.sort(key=lambda f: order[f.id])
    summary = "\n\n".join([" ".join(f.text for f in used), question])
    return summary, [f.to_dict() for f in used], question_sources


def parse_selection(response, facts):
    if response.get("done_reason") == "length":
        raise ValueError("Truncated selection")
    parsed = json.loads(response["message"]["content"])
    if not isinstance(parsed, dict) or set(parsed) != {"selected"}:
        raise ValueError("Unexpected response schema")
    selected = parsed["selected"]
    valid = {f.id for f in facts if not f.required}
    if not isinstance(selected, list) or len(selected) > 2 or any(not isinstance(x, str) or x not in valid for x in selected):
        raise ValueError("Invalid fact IDs")
    if len(set(selected)) != len(selected):
        raise ValueError("Duplicate IDs")
    return selected


def selection_schema(facts):
    valid = [f.id for f in facts if not f.required]
    return {
        "type": "object",
        "properties": {
            "selected": {
                "type": "array",
                "items": {"type": "string", **({"enum": valid} if valid else {})},
                "maxItems": min(2, len(valid)),
            }
        },
        "required": ["selected"],
        "additionalProperties": False,
    }


def select(company, facts, model, version="v3"):
    prompt = (ROOT / "prompts" / f"{version}.txt").read_text()
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps({"facts": [f.to_dict() for f in facts]})},
        ],
        "format": selection_schema(facts) if version == "v4" else SCHEMA,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "seed": 42, "num_predict": 96, "num_ctx": 8192},
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    path = ROOT / "runs" / version / f"{company['registrationNumber']}-{digest}.json"
    if path.exists():
        record = json.loads(path.read_text())
    else:
        start = time.monotonic()
        request = urllib.request.Request(
            ENDPOINT, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:  # noqa: S310 -- fixed loopback endpoint
                raw = json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError("Ollama request failed; start Ollama and check the installed model.") from exc
        record = {
            "created_at": datetime.now(UTC).isoformat(),
            "endpoint": ENDPOINT,
            "request": body,
            "response": raw,
            "elapsed_seconds": round(time.monotonic() - start, 3),
        }
        write_json(path, record)
    try:
        selected = parse_selection(record["response"], facts)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        # Keep the mandatory summary, but expose the failed selection in the evidence.
        return [], str(path.relative_to(ROOT)), record, str(exc)
    return selected, str(path.relative_to(ROOT)), record, None


def run(companies, model=MODEL, offline=False, version="v3", merge=False):
    from company_summaries import refined

    fact_builder = refined.build_facts if version == "v4" else build_facts
    renderer = refined.render if version == "v4" else render
    output_version = ("v4-rules" if version == "v4" else "rules-only") if offline else version
    out = ROOT / "summaries" / f"{output_version}.jsonl"
    evidence_path = ROOT / "evaluations" / f"{output_version}-evidence.json"
    rows, evidence = [], []
    if merge and out.exists() and evidence_path.exists():
        saved_rows, saved_evidence = read_snapshot(ROOT, output_version)
        rows = [json.loads(line) for line in saved_rows.splitlines() if line.strip()]
        evidence = json.loads(saved_evidence) if saved_evidence else []
    for i, company in enumerate(companies, 1):
        facts = fact_builder(company)
        if offline:
            ranked = refined.rank_optional(company, facts) if version == "v4" else [f.id for f in facts if not f.required][:2]
            selected, cache, record, error = ranked, None, {}, None
        else:
            selected, cache, record, error = select(company, facts, model, version)
        summary, used, question_sources = renderer(company, selected)
        row = {"registrationNumber": company["registrationNumber"], "summary": summary}
        rows = [r for r in rows if r["registrationNumber"] != row["registrationNumber"]]
        evidence = [r for r in evidence if r["registrationNumber"] != row["registrationNumber"]]
        rows.append(row)
        evidence.append(
            {
                **row,
                "selected": selected,
                "facts": used,
                "follow_up_sources": question_sources,
                "response_file": cache,
                "selection_error": error,
                "model": None if offline else model,
                "elapsed_seconds": record.get("elapsed_seconds"),
                "word_count": len(summary.split()),
            }
        )
        print(
            f"[{i}/{len(companies)}] {company['registrationNumber']}: {len(summary.split())} words"
            + (f"; selection rejected: {error}" if error else ""),
            flush=True,
        )
    # One authoritative snapshot commits both artifacts. JSONL/JSON exports are
    # restored on ordinary write failure; a crash cannot split snapshot readers.
    rows.sort(key=lambda r: r["registrationNumber"])
    evidence.sort(key=lambda r: r["registrationNumber"])
    publish(ROOT, output_version, rows, evidence)
    return rows, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", action="append", help="Run specified IDs; default is all 50")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--version", choices=["v3", "v4"], default="v4")
    parser.add_argument("--offline", action="store_true", help="Run the rules-only comparison without an LLM")
    args = parser.parse_args()
    companies = load_companies()
    if args.company:
        wanted = set(args.company)
        companies = [c for c in companies if c["registrationNumber"] in wanted]
        if len(companies) != len(wanted):
            parser.error("Unknown company ID")
    try:
        run(companies, args.model, args.offline, args.version, merge=bool(args.company))
    except RuntimeError as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
