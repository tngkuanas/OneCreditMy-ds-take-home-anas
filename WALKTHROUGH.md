# Understanding and running the project

## Start here

```bash
just setup
just serve
```

Open http://localhost:8000. The final summaries and their evidence are already saved, so you do not need Ollama to review them.

Select `SYN-000029` and compare `v1` with `v4`. The early version sounds plausible but invents audit concerns and gets the ownership count wrong. Expand the final version's evidence to check the underlying numbers. Compare `v3` with `v4` for the shorter paragraphs and explicit trend descriptions.

Then inspect `SYN-000286` for litigation, `SYN-000217` for an older audit warning, and `SYN-000302` for missing accounts.

## Explain the system in 30 seconds

“I first tried having the model write the whole paragraph. It made factual and interpretive mistakes even after a prompt revision. I changed the design so Python builds the facts and the model only selects optional detail. Important concerns cannot be dropped. I then improved the layout and added ownership, appointment dates, and interim losses. Each sentence has a source trail. The evaluation catches wrong numbers, wrong years and misleading legal claims. I still need real reader feedback before claiming the model is better than rules.”

Use that explanation only once you can follow the code and verify the examples yourself.

## The main files to understand

| File | What it does | Main idea |
|---|---|---|
| `company_summaries/facts.py` | Converts a record into sentences and source paths | Calculate figures in code; preserve critical facts |
| `company_summaries/refined.py` | Adds contextual facts and formats v4 | Describe trends, preserve interim losses and corporate ownership, split the summary into short paragraphs |
| `company_summaries/pipeline.py` | Calls Ollama, validates the chosen IDs, caches responses and writes summaries | The model chooses; Python controls the final wording |
| `company_summaries/evaluate.py` | Reads the source and checks the saved output | Check important facts without calling a model judge |
| `tests/test_summaries.py` | Exercises edge cases and intentional output corruption | Demonstrate that checks can detect meaningful errors |

`company_summaries/experiments.py` builds the additional stress cases and human-review packet. `company_summaries/report.py` profiles the data and builds the results report. `scripts/generate.py` is retained only to reproduce the early free-form experiments. The original viewer is under `app/`, with additions for evidence and check results.

`company_summaries/artifacts.py` commits a summary/evidence pair as one snapshot. The JSONL and JSON files remain exports for submission. Failed writes cannot make the viewer combine a new summary with old evidence. Evaluation rejects exports that differ from the snapshot, and old check results are hidden when the committed run changes.

## Follow one company through the code

For `SYN-000029`:

1. The latest available accounts are FY2024, even though the record date is December 2025.
2. Python calculates free cash flow as **RM 113,617 − RM 353,126 = -RM 239,509**.
3. Revenue increased between the first and last supplied years, but profit after tax decreased.
4. The model selects from a JSON schema listing only the available optional facts; required facts are already fixed.
5. The follow-up asks how spending beyond operating cash flow is funded, without claiming to know the cause.

A negative profit after tax is a loss. Negative free cash flow means capital spending exceeded operating cash flow; it does not by itself establish that the business will fail.

Look up the response file listed in `evaluations/v4-evidence.json` to see exactly what was sent to and returned by Ollama.

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

That command refreshes one company's v4 summary and preserves the other saved companies. New responses are cached immediately; output files are published after the run succeeds. Do not run two generation processes at the same time.

`just up` is the original Docker-based alternative. `just serve` runs directly in the Python environment. Stop the direct server with Ctrl+C.

## Questions to be ready for

- **Why not just write a better prompt?** Two saved attempts still produced unsupported concerns; restricting output gave stronger control.
- **Is this still LLM-based?** Yes, the model selects supporting facts, but Python owns calculations, mandatory coverage, follow-up rules, and wording.
- **Why use an LLM if rules perform similarly?** This is an experiment, and the results do not yet justify the extra complexity.
- **Does a clean audit mean a healthy company?** No; the opinion is reported without treating it as a health guarantee.
- **Are pending claims debts?** No; the claim amount is not established liability, and a judgment's direction is not supplied.
- **What does passing every check mean?** The listed requirements passed, not that usefulness or general accuracy has been proven.
- **What did adversarial review uncover?** The original evaluator could miss swapped single-year figures and incorrect audit/legal details when evidence repeated the error; the regression tests now run those examples through the complete release gate.
- **Why no risk score?** There are no outcome labels, contract context, or justified thresholds to calibrate one.
- **What would you improve first?** Ask real reviewers whether the summaries preserve what they need and save time.

## Collecting actual human feedback

`evaluations/REVIEW_PACKET.md` has 16 shuffled pairs. Eight compare v3 with v4; eight compare v4 with v4-rules. The separate `review-key.json` identifies the versions, so leave it closed while rating.

Ask someone to check the supplied records, choose A/B/tie/neither, and enter their observations into `review-ratings.json`. Then run `just evaluate`. The report counts only actual entered preferences; the shipped ratings are blank. This is a small convenience review, not an independent validation study.

The 24 stress cases are generated synthetic perturbations, not new real companies. Their results show coverage of specific scenarios. They do not establish a general hallucination rate.

## Before submitting

Read `CASE_STUDY.md`, inspect the example records, and run `just check`. Be comfortable explaining the arithmetic, the model's limited role, and the limits of the evaluation.

The required Google Form also needs your résumé and application details. The form link is in the original assessment brief in `README.md`. A slide deck is for the next interview if invited; it is not part of the initial submission requirements.
