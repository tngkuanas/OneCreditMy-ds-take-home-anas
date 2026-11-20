# Understanding and running the project

## Start here

```bash
just setup
just serve
```

Open http://localhost:8000. The final summaries and their evidence are already saved, so you do not need Ollama to review them.

Select `SYN-000029` and compare `v1` with `v3`. The early version sounds plausible but invents audit concerns and gets the ownership count wrong. Expand the final version's evidence to check the underlying numbers.

Then inspect `SYN-000286` for litigation, `SYN-000217` for an older audit warning, and `SYN-000302` for missing accounts.

## Explain the system in 30 seconds

“I first tried having the model write the whole paragraph. It made factual and interpretive mistakes even after a prompt revision. I changed the design so Python builds the facts and the model only selects optional detail. Important concerns cannot be dropped. Each sentence has a source trail, and I test the outputs against the original records. The model adds little over a rules-only comparison on this dataset, so I would test whether reviewers find it useful before making the system more complicated.”

Use that explanation only once you can follow the code and verify the examples yourself.

## The four files to understand

| File | What it does | Main idea |
|---|---|---|
| `company_summaries/facts.py` | Converts a record into sentences and source paths | Calculate figures in code; preserve critical facts |
| `company_summaries/pipeline.py` | Calls Ollama, validates the chosen IDs, caches responses and writes summaries | The model chooses; Python controls the final wording |
| `company_summaries/evaluate.py` | Reads the source and checks the saved output | Check important facts without calling a model judge |
| `tests/test_summaries.py` | Exercises edge cases and intentional output corruption | Demonstrate that checks can detect meaningful errors |

`company_summaries/report.py` profiles the data and builds the results report. `scripts/generate.py` is retained only to reproduce the early free-form experiments. The original viewer is under `app/`, with additions for evidence and check results.

## Follow one company through the code

For `SYN-000029`:

1. The latest available accounts are FY2024, even though the record date is December 2025.
2. Python calculates free cash flow as **RM 113,617 − RM 353,126 = -RM 239,509**.
3. Revenue increased between the first and last supplied years, but profit after tax decreased.
4. The model selected `cash_debt` and `persistent_fcf` as optional facts; required facts were already fixed.
5. The follow-up asks how spending beyond operating cash flow is funded, without claiming to know the cause.

Look up the response file listed in `evaluations/v3-evidence.json` to see exactly what was sent to and returned by Ollama.

## Commands

```bash
just check       # lint, type-check viewer, run tests, evaluate saved outputs
just generate    # all 50 final summaries; requires local Ollama
just baseline    # all 50 rules-only summaries; no LLM
just evaluate    # rebuild saved evaluation reports
```

For a one-company development run:

```bash
uv run python -m company_summaries.pipeline --company SYN-000029
```

That command writes a one-company `v3` output and evidence file. Run `just generate` afterwards to restore the full submission; matching cached calls are reused. Do not run two generation processes at the same time.

`just up` is the original Docker-based alternative. `just serve` runs directly in the Python environment. Stop the direct server with Ctrl+C.

## Questions to be ready for

- **Why not just write a better prompt?** Two saved attempts still produced unsupported concerns; restricting output gave stronger control.
- **Is this still LLM-based?** Yes, the model selects supporting facts, but Python owns calculations, mandatory coverage, follow-up rules, and wording.
- **Why use an LLM if rules perform similarly?** This is an experiment, and the results do not yet justify the extra complexity.
- **Does a clean audit mean a healthy company?** No; the opinion is reported without treating it as a health guarantee.
- **Are pending claims debts?** No; the claim amount is not established liability, and a judgment's direction is not supplied.
- **What does passing every check mean?** The listed requirements passed, not that usefulness or general accuracy has been proven.
- **Why no risk score?** There are no outcome labels, contract context, or justified thresholds to calibrate one.
- **What would you improve first?** Ask real reviewers whether the summaries preserve what they need and save time.

## Before submitting

Read `CASE_STUDY.md`, inspect the example records, and run `just check`. Be comfortable explaining the arithmetic, the model's limited role, and the limits of the evaluation.

The required Google Form also needs your résumé and application details. The form link is in the original assessment brief in `README.md`. A slide deck is for the next interview if invited; it is not part of the initial submission requirements.
