"""Generate one company summary through an OpenAI-compatible chat API."""

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registration_number")
    parser.add_argument("--version", default="v1", choices=["v1", "v2"], help="Reproduce an early free-form experiment")
    parser.add_argument("--ollama", action="store_true", help="Use local Ollama; no API key required")
    parser.add_argument("--dry-run", action="store_true", help="Validate input without calling the API")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.version):
        parser.error("Version must contain only letters, numbers, underscores, or hyphens")
    prompt_path = ROOT / "prompts" / f"{args.version}.txt"
    if not prompt_path.is_file():
        parser.error(f"Missing prompt: {prompt_path}")
    records = [json.loads(line) for line in (ROOT / "data/companies.jsonl").read_text().splitlines() if line.strip()]
    company = next((row for row in records if row["registrationNumber"] == args.registration_number), None)
    if company is None:
        parser.error("Company not found")
    prompt = prompt_path.read_text()
    model = os.environ.get("LLM_MODEL", "qwen3.5:9b" if args.ollama else "")
    endpoint = "http://127.0.0.1:11434/api/chat" if args.ollama else os.environ.get("LLM_CHAT_URL", "")
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(company)},
        ],
    }
    if args.ollama:
        request_body.update(stream=False, think=False, options={"temperature": 0, "num_predict": 512, "num_ctx": 8192})
    if args.dry_run:
        print(f"Ready: {args.registration_number}, prompt {args.version}; no API call made.")
        return
    key = os.environ.get("LLM_API_KEY", "")
    if not model or not endpoint or (not args.ollama and not key):
        parser.error("Set LLM_MODEL, LLM_CHAT_URL, and LLM_API_KEY in your environment")
    if urlparse(endpoint).scheme != "https" and not args.ollama:
        parser.error("LLM_CHAT_URL must use HTTPS")
    digest = hashlib.sha256(json.dumps([endpoint, request_body], sort_keys=True).encode()).hexdigest()
    cache = ROOT / "runs" / args.version / f"{args.registration_number}-{digest}.json"
    if cache.exists():
        response = json.loads(cache.read_text())["response"]
    else:
        request = urllib.request.Request(  # noqa: S310 -- HTTPS checked above; local mode uses fixed loopback
            endpoint,
            data=json.dumps(request_body).encode(),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {key}"} if key and not args.ollama else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as result:  # noqa: S310 -- URL validated above
                response = json.load(result)
        except urllib.error.URLError, TimeoutError:
            parser.exit(1, "API request failed; check your endpoint, credentials, quota, and connection.\n")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"endpoint": endpoint, "request": request_body, "response": response}, indent=2) + "\n")
    try:
        summary = response["message"]["content"] if args.ollama else response["choices"][0]["message"]["content"]
        if args.ollama and response.get("done_reason") == "length":
            parser.exit(1, f"Truncated response saved to {cache}; increase num_predict before retrying.\n")
    except KeyError, IndexError, TypeError, ValueError:
        parser.exit(1, f"Response saved to {cache}, but it did not contain a summary.\n")
    if not isinstance(summary, str) or not summary.strip():
        parser.exit(1, f"Response saved to {cache}, but the summary was empty.\n")
    output = ROOT / "summaries" / f"{args.version}.jsonl"
    existing = [json.loads(line) for line in output.read_text().splitlines() if line.strip()] if output.exists() else []
    existing = [row for row in existing if row["registrationNumber"] != args.registration_number]
    existing.append({"registrationNumber": args.registration_number, "summary": summary.strip()})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in existing))
    count = len(summary.split())
    print(f"Saved {output.relative_to(ROOT)} ({count} words).")
    if not 100 <= count <= 150:
        print("Review needed: outside the 100-150 word target.")
    print("Check every claim against the company record before accepting this summary.")


if __name__ == "__main__":
    main()
