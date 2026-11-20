# Company summaries for supplier screening

## What a good summary is for this team, and why

The summary should help a reviewer decide what to investigate next. It should not make the supplier decision for them.

I prioritised factual accuracy over polished language. A fluent paragraph that confuses profit with cash, or a court claim with an established debt, would make the review worse. The summary therefore needs to cover:

- What the company does and its recorded status.
- Revenue and profit over the available period, with financial years attached.
- Operating cash flow and spending on long-term assets.
- Material exceptions: missing accounts, negative equity, short-term funding gaps, audit warnings, and relevant litigation.
- One practical follow-up question grounded in the record.

The initial target was 100–150 words. I kept 150 as the acceptance ceiling, but dropped the minimum: a company with no accounts should receive an honest short summary, rather than a paragraph padded with speculation. A material warning should never be silently removed to meet a word limit.

I deliberately avoided a risk score. There are no supplier outcomes, sector benchmarks, contract sizes, or agreed decision thresholds in the data. A numeric score would look precise without having a defensible meaning.

## What you built

The final system covers **all 50 companies**. It is a small Python pipeline with three steps:

1. **Build verified facts.** Python reads each company, sorts the available financial years, calculates free cash flow and funding gaps, and records the source paths behind each sentence.
2. **Select supporting detail.** An LLM chooses up to two optional facts from that catalog, such as cash versus borrowings, a quick ratio, or direct ownership. It returns fact IDs as JSON, not a paragraph.
3. **Render and check.** Python includes the required facts, adds selected detail when it fits, and appends a rule-based follow-up question. Unknown IDs, malformed JSON, and truncated selections are rejected. Mandatory facts still render, but the selection error is visible and fails acceptance.

The output is `summaries/v3.jsonl`, in the supplied viewer's format. The viewer also shows the source values behind each sentence and the checks for that company. `rules-only.jsonl` is a comparison that takes the first two optional facts without calling an LLM.

I used **qwen3.5:9b through the local Ollama HTTP API**, with temperature 0, seed 42, thinking disabled, and an 8,192-token context. This is a local API, rather than one of the hosted free-tier providers suggested in the brief. The model was already installed, so this avoided keys and quota limits. The pipeline makes no hosted generation API calls. Model metadata is recorded in `evaluations/environment.json`; sampling settings do not guarantee identical output across hardware or model updates.

Every model response is saved under `runs/`. Cache keys include the prompt, facts, model name, and generation settings. The cached responses allow evaluation and regeneration without another model call. The final pipeline adds no new dependencies beyond the supplied environment.

### Why I changed the approach

The first approach asked the model to write the whole summary. On **SYN-000029**, v1 produced 207 words, described five shareholder-directors when the record lists four shareholders, and suggested audit independence concerns merely because the same audit firm appeared repeatedly.

I tightened the prompt. v2 corrected the shareholder count, but still produced 206 words, repeated the audit independence suggestion, and rounded FY2023 free cash flow of -RM 8,059 to a loss of RM 9k. These were not problems I wanted to solve with an increasingly long list of instructions.

That led to the final design: the model can decide which optional information to include, but cannot invent financial figures or write unsupported conclusions. This sacrifices some natural language variety. For this task, that is a trade-off I am comfortable making.

## How you know whether it's good

I used three forms of evidence. The saved measurements and per-company results are in [evaluations/RESULTS.md](evaluations/RESULTS.md).

### Source checks across all 50 companies

The evaluator reads the original records separately from the renderer. It checks the required amounts, years, status, historical audit exceptions, legal roles, pending-claim totals, relevant caveats, and optional figures when present. It also checks coverage, duplicate IDs, the word limit, and whether the evidence paths resolve.

The final version passes every applicable automated check for **50/50 companies**. There are no duplicate IDs or rejected model selections. Summaries range from **58 to 131 words**, with a median of **107**; **44/50** fall within the original 100–150 word target.

The data profile also checks basic statement arithmetic. All **508** tested identities match within a one-ringgit tolerance. There are **101 null ratio values**, which remain unavailable rather than being converted to zero. These checks cover a few accounting identities, not a full audit of the synthetic data or all ratio definitions.

### A selected set of difficult records

I used a **12-company challenge set**, covering missing accounts, a single reporting year, losses, negative equity, historical audit disclaimers, winding-up status, and litigation with different roles and outcomes. The expected source facts are saved separately in `evaluations/review-set.json`. All 12 pass.

Three examples matter particularly:

- **SYN-000217:** the FY2023 disclaimer remains visible even though FY2024 has an unqualified opinion.
- **SYN-000286:** pending defendant claims total RM 466,500; the summary does not treat this as proven debt, and it flags the pending winding-up petition.
- **SYN-000545:** the company is winding up despite positive reported profit, so its status and historical going-concern warning take priority over reassuring financial figures.

These are purposively selected development cases, not a held-out or representative test set. The source review was AI-assisted. I do not present it as an independent human assessment.

### Regression and mutation tests

The tests exercise errors that could change a reviewer's interpretation: reversing financial-year order, converting a null ratio to zero, treating a plaintiff claim as a defendant liability, losing an older audit warning, and accepting invented model IDs.

Mutation tests deliberately change a revenue figure, an ownership percentage, a ratio, an audit opinion, and a legal caveat. The evaluator catches these changes. This gives more useful evidence than only checking that the code runs. Run the complete checks with `just check`; no local model is needed for that command.

### What the results do not prove

Passing these checks does not establish that every sentence is the best possible summary or that reviewers make better decisions. The evaluator contains explicit rules, and the renderer uses the same task definition. There can still be omissions that neither anticipates. The fixed wording is also repetitive, and aggregation of litigation loses case-level detail; the full records remain available alongside it.

There is also limited evidence that the LLM is necessary. Its output differs from the rules-only comparison for just **4/50 companies**. Three omit the share-capital sentence for companies without financials; one selects ownership instead of a quick ratio. Both approaches pass the same required-fact checks. I would not claim that the model improves screening quality based on this result.

The 50 final model requests used **42,184 input tokens** and **639 output tokens**. Their saved request times total **426.39 seconds**, with a median of **8.92 seconds**. These are observed local inference times, not total development time or hosted API benchmarks. There were no billed API calls; hardware and electricity costs were not measured.

## What you'd do next, and how you'd keep improving it

My next step would be a small review exercise with the people who vet suppliers. I would show the rules-only and model-selected summaries in random order, ask which information they missed, and measure how quickly they identify the issues that require follow-up. I would agree the rubric before collecting those results.

If the model does not improve relevance or reduce review time, I would keep the rules-only version. The current experiment gives no reason to pay an ongoing inference cost simply to retain an LLM in the architecture.

For a second iteration, I would focus on:

1. **Contract context:** let reviewers specify the contract size and service so the summary can prioritise relevant concerns without inventing universal risk thresholds.
2. **Coverage beyond the current rules:** test material director changes, foreign corporate ownership, middle-year reversals, and case-specific details that a short aggregate may obscure.
3. **Freshness and monitoring:** show the record date prominently, refresh summaries when records change, and track failed checks, selection errors, missing fields, and reviewer corrections.
4. **A genuinely unseen evaluation set:** retain a fixed regression set, add reviewed failures to it, and test each change against records that were not used to design the rules.

This submission is a complete prototype with saved outputs and reproducible checks. It has no production deployment, calibrated credit model, or measured impact on supplier decisions.

**AI assistance:** Codex assisted with implementation, prompts, source comparisons, tests, documentation, and drafting this case study. The local Qwen model generated v1 and v2 and selected optional facts for v3. No independent human evaluation is claimed. The decisions and limitations above should be reviewed and understood before this is submitted or presented.
