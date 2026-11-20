# Results

Generated from saved artifacts by `just evaluate`; no model calls are made by evaluation.

## Dataset

- 50 synthetic companies, as of 2025-12-31.
- Financial years per company: {0: 3, 1: 5, 2: 4, 3: 38}.
- Company statuses: {'Active': 48, 'Winding up': 2}.
- 72 court cases; {'plaintiff': 32, 'defendant': 40}.
- 101 unavailable ratio values; nulls are never treated as zero.
- 508 statement arithmetic checks; 0 discrepancies above RM 1.

## Experiments

| Version | Companies | Words (min / median / max) | Automated acceptance |
|---|---:|---:|---|
| v1 | 1 | 207 / 207 / 207 | 0/1 |
| v2 | 1 | 206 / 206 / 206 | 0/1 |
| rules-only | 50 | 71 / 107 / 131 | 50/50 |
| v3 | 50 | 58 / 107 / 131 | 50/50 |
| v4-rules | 50 | 60 / 112 / 142 | 50/50 |
| v4 | 50 | 52 / 104.5 / 134 | 50/50 |

v1 and v2 each cover only SYN-000029. Their automated checks are limited to identity, length, and known unsupported audit claims; exact wording checks would unfairly penalize free-form prose. See `first-review.json` for the actual source-comparison findings. No population-level baseline accuracy is claimed.

## Final acceptance checks

- Coverage: 50/50; duplicate IDs: 0.
- Applicable checks passed: 1386/1386.
- Source-read challenge cases passed: 12/12.
- Summaries within the original 100-150 word target: 34/50.
- Shorter summaries are allowed when extra detail adds little, especially for sparse records; there is no padding.
- Safety facts take precedence over the word budget; an over-budget output would fail acceptance rather than silently lose a warning.

These checks cover specified facts, legal caveats, length, and evidence paths. They are not a measured hallucination rate or proof of reader usefulness. The challenge set is purposive, AI-assisted, and not held out.

## Does the LLM earn its place?

The final output differs from the rules-only comparison for **48/50 companies**. Required facts and follow-up rules are identical by design. Neither method is shown to improve a reviewer's decisions. The rules-only baseline is a credible simpler alternative, not a deliberately weak benchmark.

## Local inference

- Model: `qwen3.5:9b` via Ollama, temperature 0, seed 42, thinking disabled.
- 50 saved requests; 0 rejected selections.
- Sum of saved first-run request times: 462.33 seconds; median request: 9.40 seconds.
- Reported tokens: 44,822 input; 441 output.
- These are observed local timings, not hosted API benchmarks or total project work time.
- There were no billed API calls; electricity and hardware costs are unmeasured.

## Reproduce

```bash
just check
# Optional: regenerate using the installed local model
just generate
just evaluate
```

## Refinement and additional checks

- Required-field checks bind amounts to years and fields; including both numbers somewhere is insufficient.
- Majority corporate owners are included; director appointments use the record date, without inferring governance problems.
- Interim losses between profitable endpoints cannot be hidden by first-versus-last comparisons.
- When the latest profit direction conflicts with the endpoint trend, the latest comparison is mandatory.
- Full-gate mutation tests cover single-year field swaps, wrong years, invented audit opinions and wrong legal counts.
- A single committed snapshot binds summary and evidence; exports must match it. The viewer rejects stale evaluation revisions and shows the previous snapshot after interrupted publication.
- Synthetic stress requirements: v3 12/24; v4 24/24.
- These are synthetic regression requirements, including newly added coverage; they are not independent real-company accuracy measurements.
- Stress tests request relevant optional facts explicitly, isolating fact extraction and rendering from model prioritisation. Human comparison is still pending.
- Median paragraphs per summary: v3 2; v4 4.
- Paragraph count describes layout only; reader comprehension has not been measured.
- The initial v4 trial rejected 5/50 selections. The final run constrains the model's JSON schema to the available optional IDs. The trial responses remain saved.
- Human comparison packet: 0/16 pairs rated; status: pending_human_review.
- No human preference or review-time improvement is claimed. Use REVIEW_PACKET.md and review-ratings.json to collect actual observations.
